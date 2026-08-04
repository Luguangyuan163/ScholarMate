"""PDF 接口（P2/P4 接入）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/pdf", tags=["pdf"])


@router.post("/upload")
async def upload_pdf() -> JSONResponse:
    return JSONResponse(status_code=501, content={"detail": "PDF 上传将在 P2 实现"})


@router.post("/{pdf_id}/translate")
async def translate_pdf(pdf_id: int) -> JSONResponse:
    return JSONResponse(status_code=501, content={"detail": "PDF 翻译将在 P4 实现"})
