"""PDF 接口：上传入库（提取 → 分块 → 向量化），翻译在 P4 接入。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Annotated
from uuid import uuid4

import aiofiles
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.sse import sse_response
from app.core.database import get_db
from app.models.translation_record import TranslationRecord
from app.models.uploaded_pdf import UploadedPDF
from app.schemas.pdf import PDFImportRequest, PDFUploadResponse, TranslateRequest

router = APIRouter(prefix="/api/pdf", tags=["pdf"])
logger = logging.getLogger(__name__)
TRANSLATE_CHUNK_CHARS = 2000
TRANSLATE_BATCH_SIZE = 4
TRANSLATE_HEARTBEAT_SECONDS = 10.0
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
    """校验 → 落盘 → 建记录(processing) → 立即返回；提取/向量化转入后台任务。"""
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

    request.app.state.processing_progress[record.id] = {
        "stage": "extracting",
        "done": 0,
        "total": 0,
    }
    asyncio.create_task(
        _process_pdf_background(
            request,
            record.id,
            str(path),
            original_name,
        )
    )
    return PDFUploadResponse(
        pdf_id=record.id,
        filename=original_name,
        status=record.status,
    )


async def _process_pdf_background(
    request: Request,
    pdf_id: int,
    path: str,
    original_name: str,
) -> None:
    """后台执行 提取 → 分块 → 向量化 → 写库；进度写入 processing_progress。"""
    progress = request.app.state.processing_progress
    db = request.app.state.database
    pdf_service = request.app.state.pdf_service
    embedding_service = request.app.state.embedding_service
    vector_store = request.app.state.vector_store
    try:
        result = await run_in_threadpool(pdf_service.extract, path)
        chunks = pdf_service.chunk_paragraphs(result.text)
        async with db.session_factory() as session:
            row = await session.get(UploadedPDF, pdf_id)
            row.page_count = result.page_count
            await session.commit()

        def _report(done: int, total: int) -> None:
            progress[pdf_id] = {"stage": "embedding", "done": done, "total": total}

        vectors = await embedding_service.embed_texts(chunks, on_batch=_report)
        await run_in_threadpool(
            vector_store.add_document, pdf_id, original_name, chunks, vectors
        )
        async with db.session_factory() as session:
            row = await session.get(UploadedPDF, pdf_id)
            row.status = "ready"
            await session.commit()
        progress[pdf_id] = {"stage": "done", "done": len(chunks), "total": len(chunks)}
    except Exception as exc:
        logger.warning("PDF %s 后台处理失败: %s", pdf_id, exc)
        async with db.session_factory() as session:
            row = await session.get(UploadedPDF, pdf_id)
            row.status = "failed"
            await session.commit()
        progress[pdf_id] = {"stage": "failed", "done": 0, "total": 0}


@router.get("/{pdf_id}/status")
async def pdf_status(
    pdf_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """查询上传处理状态：status + 后台阶段/进度（供前端轮询）。"""
    row = await session.get(UploadedPDF, pdf_id)
    if row is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    progress = request.app.state.processing_progress.get(pdf_id, {})
    return {
        "pdf_id": pdf_id,
        "status": row.status,
        "stage": progress.get("stage", row.status),
        "done": progress.get("done", 0),
        "total": progress.get("total", 0),
    }


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


@router.get("/{pdf_id}/pages/{page_number}/image")
async def pdf_page_image(
    pdf_id: int,
    page_number: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    scale: float = Query(default=2.0, ge=1.0, le=4.0),
) -> Response:
    """按页渲染原 PDF 为 PNG（保留排版），供对照翻译的原文预览使用。"""
    row = await session.get(UploadedPDF, pdf_id)
    if row is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    pdf_service = request.app.state.pdf_service
    try:
        png = await run_in_threadpool(
            pdf_service.render_page, row.file_path, page_number - 1, scale
        )
        total_pages = row.page_count or await run_in_threadpool(
            pdf_service.page_count, row.file_path
        )
    except (IndexError, OSError) as exc:
        raise HTTPException(status_code=404, detail="PDF 页面不可用") from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Total-Pages": str(total_pages),
        },
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
    if row.status not in {"ready", "processing"}:
        raise HTTPException(status_code=409, detail="论文处理失败，无法翻译")

    return sse_response(
        _pdf_translate_events(request, row, payload)
    )


@router.get("/{pdf_id}/translate-stream")
async def translate_pdf_stream(
    pdf_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    target_lang: str = Query(default="zh", max_length=16),
    max_paragraphs: int = Query(default=0, ge=0, le=500),
):
    """EventSource 使用的 GET 翻译流式端点。"""
    row = await session.get(UploadedPDF, pdf_id)
    if row is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    if row.status not in {"ready", "processing"}:
        raise HTTPException(status_code=409, detail="论文处理失败，无法翻译")
    payload = TranslateRequest(
        target_lang=target_lang,
        max_paragraphs=max_paragraphs,
    )
    return sse_response(_pdf_translate_events(request, row, payload))


async def _pdf_translate_events(request: Request, row, payload: TranslateRequest):
    pdf_service = request.app.state.pdf_service
    translation = request.app.state.translation_service
    async for event in _translate_events(
        request, pdf_service, translation, row, payload
    ):
        yield event


async def _translate_events(
    request: Request,
    pdf_service,
    translation,
    row,
    payload: TranslateRequest,
):
    """提取正文（剔除图表文字）→ 分块 → 复用缓存 + 并发逐段翻译，产出 SSE 事件。"""
    result = await run_in_threadpool(pdf_service.extract_clean, row.file_path)
    chunks = pdf_service.chunk_paragraphs(result.text, max_chars=TRANSLATE_CHUNK_CHARS)
    if payload.max_paragraphs > 0:
        chunks = chunks[: payload.max_paragraphs]
    total = len(chunks)
    yield {"type": "progress", "done": 0, "total": total}

    cache = await _load_translation_cache(request, row, payload.target_lang)
    segments_by_index: dict[int, dict] = {}
    pending_indexes: list[int] = []
    pending_texts: list[str] = []

    for index, chunk in enumerate(chunks):
        cached = cache.get(chunk)
        if cached is not None:
            segments_by_index[index] = {"source": chunk, "translation": cached}
            yield {
                "type": "segment",
                "index": index,
                "source": chunk,
                "translation": cached,
                "total": total,
            }
        else:
            pending_indexes.append(index)
            pending_texts.append(chunk)

    if pending_texts:
        try:
            async for event in _translate_pending_with_heartbeat(
                translation,
                pending_texts,
                pending_indexes,
                chunks,
                total,
                payload.target_lang,
            ):
                if event["type"] == "segment":
                    segments_by_index[event["index"]] = {
                        "source": event["source"],
                        "translation": event["translation"],
                    }
                yield event
        except Exception as exc:
            yield {"type": "error", "content": f"翻译失败: {exc}"}
            return

    segments = [segments_by_index[index] for index in sorted(segments_by_index)]
    await _save_translation(request, row, payload.target_lang, segments)
    yield {"type": "done", "total": total}


async def _translate_pending_with_heartbeat(
    translation,
    pending_texts: list[str],
    pending_indexes: list[int],
    chunks: list[str],
    total: int,
    target_lang: str,
) -> AsyncIterator[dict]:
    """逐段并发翻译：先完成先输出；等待期间每隔一段时间发 status 心跳。"""
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    async def _worker() -> None:
        try:
            async for offset, text in translation.translate_paragraphs_concurrent(
                pending_texts,
                target_lang,
                max_concurrency=TRANSLATE_BATCH_SIZE,
            ):
                await queue.put(("segment", offset, text))
        except Exception as exc:
            await queue.put(("error", exc))
        finally:
            await queue.put((sentinel, None, None))

    task = asyncio.create_task(_worker())
    done_count = 0
    try:
        while True:
            try:
                kind, offset, text = await asyncio.wait_for(
                    queue.get(), timeout=TRANSLATE_HEARTBEAT_SECONDS
                )
            except TimeoutError:
                remaining = len(pending_texts) - done_count
                yield {
                    "type": "status",
                    "content": (
                        f"正在翻译剩余 {remaining} 段"
                        f"（已输出 {done_count}/{total} 段）…"
                    ),
                    "done": done_count,
                    "total": total,
                }
                continue
            if kind is sentinel:
                return
            if kind == "error":
                raise RuntimeError(str(text))
            index = pending_indexes[offset]
            done_count += 1
            yield {
                "type": "segment",
                "index": index,
                "source": chunks[index],
                "translation": text,
                "total": total,
            }
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _load_translation_cache(
    request: Request, row, target_lang: str
) -> dict[str, str]:
    """读取该 PDF 最近一次同语言翻译记录，作为断点续翻缓存。"""
    db = request.app.state.database
    async with db.session_factory() as session:
        record = await session.scalar(
            select(TranslationRecord)
            .where(
                TranslationRecord.pdf_id == row.id,
                TranslationRecord.target_lang == target_lang,
            )
            .order_by(TranslationRecord.created_at.desc())
            .limit(1)
        )
        if record is None:
            return {}
        segments = json.loads(record.segments_json or "[]")
    return {
        segment["source"]: segment["translation"]
        for segment in segments
        if segment.get("source") is not None
    }


async def _save_translation(request: Request, row, target_lang: str, segments: list) -> None:
    """翻译完成后持久化版本，供后续对照查看。"""
    db = request.app.state.database
    async with db.session_factory() as session:
        session.add(
            TranslationRecord(
                pdf_id=row.id,
                filename=row.original_name,
                target_lang=target_lang,
                segments_json=json.dumps(segments, ensure_ascii=False),
                total=len(segments),
            )
        )
        await session.commit()
