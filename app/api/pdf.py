"""PDF 接口：上传入库（提取 → 分块 → 向量化），翻译在 P4 接入。"""

from __future__ import annotations

import json
from typing import Annotated
from uuid import uuid4

import aiofiles
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models.uploaded_pdf import UploadedPDF
from app.schemas.pdf import PDFImportRequest, PDFUploadResponse, TranslateRequest

router = APIRouter(prefix="/api/pdf", tags=["pdf"])
TRANSLATE_CHUNK_CHARS = 2000
DOWNLOAD_TIMEOUT_SECONDS = 30.0
DOWNLOAD_USER_AGENT = "ScholarMate/0.1 (graduation project)"


@router.post("/upload", response_model=PDFUploadResponse)
async def upload_pdf(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(...)],
) -> PDFUploadResponse:
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    content = await file.read()
    return await _store_and_process(request, session, content, filename)


@router.post("/import-url", response_model=PDFUploadResponse)
async def import_pdf_from_url(
    request: Request,
    payload: PDFImportRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PDFUploadResponse:
    """从外部 URL 下载 PDF 并入库（检索结果一键导入翻译）。"""
    try:
        content = await _download_pdf(payload.url)
    except httpx.UnsupportedProtocol as exc:
        raise HTTPException(status_code=400, detail="PDF 下载地址无效") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"PDF 下载失败（HTTP {exc.response.status_code}）",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail="PDF 下载失败，请检查链接") from exc

    original_name = (
        f"{payload.title.strip()[:80]}.pdf"
        if payload.title.strip()
        else "remote_paper.pdf"
    )
    return await _store_and_process(request, session, content, original_name)


async def _download_pdf(url: str) -> bytes:
    async with httpx.AsyncClient(
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
        headers={"User-Agent": DOWNLOAD_USER_AGENT},
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


async def _store_and_process(
    request: Request,
    session: AsyncSession,
    content: bytes,
    original_name: str,
) -> PDFUploadResponse:
    """校验 → 落盘 → 建记录 → 提取/分块/向量化，上传与 URL 导入共用。"""
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="文件内容不是有效的 PDF")
    settings = request.app.state.settings
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
        original_name=original_name,
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
            vector_store.add_document, record.id, original_name, chunks, vectors
        )
        record.status = "ready"
        record.page_count = result.page_count
        await session.commit()
    except Exception as exc:
        record.status = "failed"
        await session.commit()
        raise HTTPException(status_code=500, detail=f"PDF 处理失败: {exc}") from exc

    return PDFUploadResponse(
        pdf_id=record.id, filename=original_name, status=record.status
    )


@router.get("/{pdf_id}/file")
async def download_pdf_file(
    pdf_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    """以 inline 方式返回本地 PDF，供浏览器/系统查看器直接打开。"""
    row = await session.get(UploadedPDF, pdf_id)
    if row is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return FileResponse(
        row.file_path,
        media_type="application/pdf",
        filename=row.original_name,
        content_disposition_type="inline",
    )


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
