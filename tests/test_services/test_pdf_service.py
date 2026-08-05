"""PDF 服务测试：文本提取与段落分块。"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from app.services.pdf_service import PDFService, _normalize_text


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


def test_normalize_text_decomposes_ligatures():
    assert _normalize_text("ﬁne-tuning is eﬃcient") == "fine-tuning is efficient"
    assert _normalize_text("ﬀ ﬂ ﬃ ﬄ") == "ff fl ffi ffl"


def test_render_page_returns_png(tmp_path):
    pdf_path = tmp_path / "page.pdf"
    _make_pdf(pdf_path, ["First page", "Second line"])
    service = PDFService()
    png = service.render_page(str(pdf_path), 0, scale=2.0)
    assert png.startswith(b"\x89PNG")
    assert len(png) > 1000


def test_render_page_out_of_range_raises(tmp_path):
    pdf_path = tmp_path / "short.pdf"
    _make_pdf(pdf_path, ["Only one page"])
    service = PDFService()
    with pytest.raises(IndexError):
        service.render_page(str(pdf_path), 3, scale=2.0)


def test_page_count(tmp_path):
    pdf_path = tmp_path / "multi.pdf"
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), "Page")
    doc.save(str(pdf_path))
    doc.close()
    service = PDFService()
    assert service.page_count(str(pdf_path)) == 3


def _make_figure_table_pdf(path: Path) -> None:
    """构造含图片（图内有文字）与表格的 PDF，用于验证图表文字过滤。"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Body paragraph that should be translated.")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 120))
    pix.set_rect(fitz.IRect(0, 0, 200, 120), (230, 230, 230))
    page.insert_image(fitz.Rect(72, 150, 400, 300), pixmap=pix)
    page.insert_text((100, 200), "Axis label inside figure")
    page.insert_text((72, 330), "Figure 1: caption below figure.")
    x0, y0 = 72, 400
    for i in range(3):
        for j in range(2):
            rect = fitz.Rect(
                x0 + j * 120, y0 + i * 40, x0 + (j + 1) * 120, y0 + (i + 1) * 40
            )
            page.draw_rect(rect, color=(0, 0, 0), width=0.7)
    page.insert_text((x0 + 10, y0 + 25), "Cell A")
    page.insert_text((x0 + 130, y0 + 25), "Cell B")
    page.insert_text((x0 + 10, y0 + 65), "Cell C")
    doc.save(str(path))
    doc.close()


def test_extract_clean_skips_figure_and_table_text(tmp_path):
    pdf_path = tmp_path / "figtable.pdf"
    _make_figure_table_pdf(pdf_path)
    service = PDFService()
    result = service.extract_clean(str(pdf_path))
    assert "Body paragraph" in result.text
    assert "Figure 1" in result.text
    assert "Axis label inside figure" not in result.text
    assert "Cell A" not in result.text
    assert "Cell B" not in result.text
    assert "Cell C" not in result.text
    assert result.page_count == 1


def test_extract_keeps_figure_and_table_text(tmp_path):
    """原始 extract 保持全文不变，仅 extract_clean 用于翻译过滤。"""
    pdf_path = tmp_path / "figtable.pdf"
    _make_figure_table_pdf(pdf_path)
    service = PDFService()
    raw = service.extract(str(pdf_path))
    assert "Axis label inside figure" in raw.text
    assert "Cell A" in raw.text
