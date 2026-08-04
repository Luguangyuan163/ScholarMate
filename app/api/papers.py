"""论文库管理接口：列表与删除。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models.uploaded_pdf import UploadedPDF

router = APIRouter(prefix="/api/papers", tags=["papers"])


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
