"""PDF 文本提取与分块（P2 接入）。

PyMuPDF / pdfplumber 为同步库，调用方需经 anyio.to_thread 执行。
"""

from __future__ import annotations


class PDFService:
    async def extract_text(self, pdf_path: str) -> str:
        raise NotImplementedError("PDF 文本提取将在 P2 接入")

    async def split_paragraphs(self, text: str) -> list[str]:
        raise NotImplementedError("PDF 分块将在 P2 接入")
