"""论文库管理接口：列表与删除。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models.paper import Paper
from app.models.uploaded_pdf import UploadedPDF
from app.schemas.paper import PaperImportRequest

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.post("/import")
async def import_papers(
    payload: PaperImportRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """批量收藏论文元数据；已存在时更新引用量/年份，保持论文库最新。"""
    imported = 0
    updated = 0
    skipped = 0
    for item in payload.papers:
        exists = await session.execute(
            select(Paper).where(
                Paper.source == item.source,
                Paper.external_id == item.external_id,
            )
        )
        existing = exists.scalar_one_or_none()
        if existing is not None:
            if (
                item.citation_count > existing.citation_count
                or item.year != existing.year
            ):
                existing.citation_count = item.citation_count
                existing.year = item.year
                existing.url = item.url
                updated += 1
            else:
                skipped += 1
            continue
        session.add(
            Paper(
                title=item.title,
                authors=json.dumps(item.authors, ensure_ascii=False),
                abstract=item.abstract,
                source=item.source,
                external_id=item.external_id,
                year=item.year,
                citation_count=item.citation_count,
                url=item.url,
            )
        )
        imported += 1
    await session.commit()
    return {"imported": imported, "updated": updated, "skipped": skipped}


@router.get("/collection")
async def list_collection(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    rows = (
        await session.execute(select(Paper).order_by(Paper.created_at.desc()))
    ).scalars().all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "authors": json.loads(row.authors or "[]"),
            "abstract": row.abstract,
            "source": row.source,
            "external_id": row.external_id,
            "year": row.year,
            "citation_count": row.citation_count,
            "url": row.url,
        }
        for row in rows
    ]


@router.delete("/collection/{paper_id}")
async def delete_collection_paper(
    paper_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    row = await session.get(Paper, paper_id)
    if row is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    await session.delete(row)
    await session.commit()
    return {"deleted": paper_id}


@router.get("")
async def list_papers(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    result = await session.execute(
        select(UploadedPDF).order_by(UploadedPDF.created_at.desc())
    )
    rows = result.scalars().all()
    return [
        {
            "id": row.id,
            "filename": row.original_name,
            "status": row.status,
            "page_count": row.page_count,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.delete("/{pdf_id}")
async def delete_paper(
    pdf_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    row = await session.get(UploadedPDF, pdf_id)
    if row is None:
        raise HTTPException(status_code=404, detail="论文不存在")

    upload_dir = request.app.state.settings.pdf_upload_dir
    file_path = Path(row.file_path).resolve()
    if not file_path.is_relative_to(upload_dir.resolve()):
        raise HTTPException(status_code=400, detail="论文文件路径异常，拒绝删除")

    vector_store = request.app.state.vector_store
    await run_in_threadpool(vector_store.delete_document, pdf_id)
    if file_path.exists():
        file_path.unlink()
    await session.delete(row)
    await session.commit()
    return {"deleted": pdf_id}
