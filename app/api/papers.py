"""论文库管理接口：本地 PDF 论文的列表、入库（自动下载 PDF）与删除。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.pdf import _download_pdf, _store_and_process
from app.core.database import get_db
from app.models.uploaded_pdf import UploadedPDF
from app.schemas.paper import BatchDeleteRequest, PaperImportRequest

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.post("/import-pdf")
async def import_papers_as_pdf(
    payload: PaperImportRequest,
    request: Request,
) -> dict:
    """把论文以 PDF 形式下载存入本地论文库；链接不可下载的跳过并说明原因。"""
    imported = 0
    failed: list[dict] = []
    for item in payload.papers:
        url = _resolve_pdf_url(item)
        if not url:
            failed.append({"title": item.title, "reason": "未找到可下载的 PDF 链接"})
            continue
        name = f"{item.title.strip()[:80]}.pdf" if item.title.strip() else "paper.pdf"
        try:
            content = await _download_pdf(url)
        except httpx.HTTPError as exc:
            failed.append({"title": item.title, "reason": f"下载失败: {exc}"})
            continue
        if not content.startswith(b"%PDF"):
            failed.append({"title": item.title, "reason": "下载内容不是有效的 PDF"})
            continue
        async with request.app.state.database.session_factory() as session:
            duplicate = await session.scalar(
                select(UploadedPDF).where(UploadedPDF.original_name == name)
            )
            if duplicate is not None:
                failed.append({"title": item.title, "reason": "已在论文库中"})
                continue
            await _store_and_process(request, session, content, name)
        imported += 1
    return {"imported": imported, "failed": failed}


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


def _resolve_pdf_url(item) -> str:
    """优先使用论文的 PDF 直链；arXiv 收藏可推导官方 PDF 地址。"""
    if item.pdf_url:
        return item.pdf_url
    if item.source == "arxiv" and item.external_id:
        return f"https://arxiv.org/pdf/{item.external_id}"
    return ""


@router.post("/batch-delete")
async def batch_delete_papers(
    payload: BatchDeleteRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """批量删除本地论文库（含磁盘文件与向量索引），路径越界的记录跳过。"""
    ids = list(dict.fromkeys(payload.ids))
    if not ids:
        return {"deleted": 0, "requested": 0}

    rows = (
        (
            await session.execute(
                select(UploadedPDF).where(UploadedPDF.id.in_(ids))
            )
        )
        .scalars()
        .all()
    )
    upload_dir = request.app.state.settings.pdf_upload_dir.resolve()
    vector_store = request.app.state.vector_store
    deleted = 0
    for row in rows:
        file_path = Path(row.file_path).resolve()
        if not file_path.is_relative_to(upload_dir):
            continue
        await run_in_threadpool(vector_store.delete_document, row.id)
        if file_path.exists():
            file_path.unlink()
        await session.delete(row)
        deleted += 1
    await session.commit()
    return {"deleted": deleted, "requested": len(ids)}
