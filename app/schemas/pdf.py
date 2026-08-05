"""PDF 接口的请求/响应模型（P2 接入）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PDFUploadResponse(BaseModel):
    pdf_id: int
    filename: str
    status: str


class TranslateRequest(BaseModel):
    target_lang: str = "zh"
    max_paragraphs: int = 0  # 0 表示翻译全部段落


class PDFImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    title: str = Field(default="", max_length=200)
