"""PDF 接口：上传入库（提取 → 分块 → 向量化），翻译在 P4 接入。"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models.uploaded_pdf import UploadedPDF
from app.schemas.pdf import PDFUploadResponse

router = APIRouter(prefix="/api/pdf", tags=["pdf"])


@router.post("/upload", response_model=PDFUploadResponse)
async def upload_pdf(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(...)],
) -> PDFUploadResponse:
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    settings = request.app.state.settings
    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"文件超过 {settings.max_upload_mb}MB 限制"
        )

    stored_name = f"{uuid4().hex}.pdf"
    path = settings.pdf_upload_dir / stored_name
    async with aiofiles.open(path, "wb") as handle:
        await handle.write(content)

    record = UploadedPDF(
        filename=stored_name,
        original_name=filename,
        file_path=str(path),
        status="processing",
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)

    pdf_service = request.app.state.pdf_service
    embedding_service = request.app.state.embedding_service
    vector_store = request.app.state.vector_store
    try:
        result = await run_in_threadpool(pdf_service.extract, str(path))
        chunks = pdf_service.chunk_paragraphs(result.text)
        vectors = await embedding_service.embed_texts(chunks)
        await run_in_threadpool(
            vector_store.add_document, record.id, filename, chunks, vectors
        )
        record.status = "ready"
        record.page_count = result.page_count
        await session.commit()
    except Exception as exc:
        record.status = "failed"
        await session.commit()
        raise HTTPException(status_code=500, detail=f"PDF 处理失败: {exc}") from exc

    return PDFUploadResponse(pdf_id=record.id, filename=filename, status=record.status)


@router.post("/{pdf_id}/translate")
async def translate_pdf(pdf_id: int) -> dict:
    raise HTTPException(status_code=501, detail="PDF 翻译将在 P4 实现")
