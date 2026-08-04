"""PDF 服务测试：文本提取与段落分块。"""

from __future__ import annotations

from pathlib import Path

import fitz

from app.services.pdf_service import PDFService


def _make_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line)
        y += 24
    doc.save(str(path))
    doc.close()


def test_extract_text(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    _make_pdf(pdf_path, ["Low-Rank Adaptation (LoRA)", "Efficient fine-tuning."])
    service = PDFService()
    result = service.extract(str(pdf_path))
    assert result.page_count == 1
    assert "LoRA" in result.text
    assert "fine-tuning" in result.text


def test_chunk_paragraphs_respects_max_chars():
    service = PDFService()
    paragraphs = [f"段落 {i} " + "内容" * 60 for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = service.chunk_paragraphs(text, max_chars=800)
    assert len(chunks) > 1
    assert all(len(chunk) <= 800 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_chunk_paragraphs_empty():
    service = PDFService()
    assert service.chunk_paragraphs("") == []
