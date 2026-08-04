"""PDF 接口的请求/响应模型（P2 接入）。"""

from __future__ import annotations

from pydantic import BaseModel


class PDFUploadResponse(BaseModel):
    pdf_id: int
    filename: str
    status: str


class TranslateRequest(BaseModel):
    target_lang: str = "zh"
    max_paragraphs: int = 0  # 0 表示翻译全部段落
