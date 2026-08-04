"""PDF 接口：上传入库（提取 → 分块 → 向量化），翻译在 P4 接入。"""

from __future__ import annotations

import json
from typing import Annotated
from uuid import uuid4

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models.uploaded_pdf import UploadedPDF
from app.schemas.pdf import PDFUploadResponse, TranslateRequest

router = APIRouter(prefix="/api/pdf", tags=["pdf"])
TRANSLATE_CHUNK_CHARS = 2000


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
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="文件内容不是有效的 PDF")
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
async def translate_pdf(
    pdf_id: int,
    payload: TranslateRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    row = await session.get(UploadedPDF, pdf_id)
    if row is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    if row.status != "ready":
        raise HTTPException(status_code=409, detail="论文尚未处理完成，请稍后重试")

    pdf_service = request.app.state.pdf_service
    translation = request.app.state.translation_service

    async def event_stream():
        async for event in _translate_events(
            pdf_service, translation, row.file_path, payload
        ):
            yield (
                f"event: {event['type']}\n"
                f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _translate_events(
    pdf_service,
    translation,
    file_path: str,
    payload: TranslateRequest,
):
    """提取全文 → 分块 → 逐段翻译，产出 SSE 事件（progress/segment/done/error）。"""
    result = await run_in_threadpool(pdf_service.extract, file_path)
    chunks = pdf_service.chunk_paragraphs(result.text, max_chars=TRANSLATE_CHUNK_CHARS)
    if payload.max_paragraphs > 0:
        chunks = chunks[: payload.max_paragraphs]
    total = len(chunks)
    yield {"type": "progress", "done": 0, "total": total}
    for index, chunk in enumerate(chunks):
        try:
            translated = await translation.translate_paragraph(chunk, payload.target_lang)
        except Exception as exc:
            yield {"type": "error", "content": f"第 {index + 1} 段翻译失败: {exc}"}
            return
        yield {
            "type": "segment",
            "index": index,
            "source": chunk,
            "translation": translated,
            "total": total,
        }
    yield {"type": "done", "total": total}
