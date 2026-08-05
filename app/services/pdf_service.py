"""PDF 文本提取与分块（P2）。

PyMuPDF 为同步库，调用方需经线程池（run_in_threadpool）执行。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import fitz


@dataclass
class PDFExtractResult:
    text: str
    page_count: int


class PDFService:
    def extract(self, pdf_path: str) -> PDFExtractResult:
        """提取 PDF 全文。"""
        with fitz.open(pdf_path) as doc:
            pages = [page.get_text("text") for page in doc]
            return PDFExtractResult(
                text=_normalize_text("\n".join(pages)), page_count=len(pages)
            )

    def extract_clean(self, pdf_path: str) -> PDFExtractResult:
        """提取正文文本，剔除图表区域文字（图片内文字、表格单元格），供翻译使用。"""
        with fitz.open(pdf_path) as doc:
            pages_text = []
            for page in doc:
                image_bboxes = [
                    fitz.Rect(info["bbox"]) for info in page.get_image_info()
                ]
                table_bboxes = [
                    fitz.Rect(table.bbox) for table in page.find_tables().tables
                ]
                kept = []
                for block in page.get_text("blocks"):
                    if block[6] != 0:
                        continue
                    text = block[4].strip()
                    if not text:
                        continue
                    rect = fitz.Rect(block[:4])
                    if _overlaps_image(rect, image_bboxes) or _inside_table(
                        rect, table_bboxes
                    ):
                        continue
                    kept.append(text)
                pages_text.append("\n\n".join(kept))
            return PDFExtractResult(
                text=_normalize_text("\n\n".join(pages_text)),
                page_count=len(pages_text),
            )

    def page_count(self, pdf_path: str) -> int:
        """返回 PDF 总页数。"""
        with fitz.open(pdf_path) as doc:
            return doc.page_count

    def render_page(
        self,
        pdf_path: str,
        page_index: int,
        scale: float = 2.0,
    ) -> bytes:
        """将指定页渲染为 PNG，保留原始排版；页码越界抛 IndexError。"""
        with fitz.open(pdf_path) as doc:
            if page_index < 0 or page_index >= doc.page_count:
                raise IndexError(f"page {page_index} out of range")
            page = doc.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            return pixmap.tobytes("png")

    def chunk_paragraphs(self, text: str, max_chars: int = 800) -> list[str]:
        """按段落累积分块，每块不超过 max_chars 字符。"""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(current) + len(paragraph) + 1 <= max_chars:
                current = f"{current}\n{paragraph}" if current else paragraph
            else:
                if current:
                    chunks.append(current)
                current = paragraph
        if current:
            chunks.append(current)
        return chunks


def _normalize_text(text: str) -> str:
    """NFKC 规范化：分解 PDF 连字（ﬁ→fi 等），统一兼容字符。"""
    return unicodedata.normalize("NFKC", text)


def _overlaps_image(
    rect: fitz.Rect,
    image_bboxes: list[fitz.Rect],
    ratio: float = 0.4,
) -> bool:
    """文本块与任一图片区域重叠比例达到阈值时，视为图内文字。"""
    area = rect.get_area()
    if area <= 0:
        return False
    for image in image_bboxes:
        intersection = rect & image
        if not intersection.is_empty and intersection.get_area() / area >= ratio:
            return True
    return False


def _inside_table(rect: fitz.Rect, table_bboxes: list[fitz.Rect]) -> bool:
    """文本块中心落在表格区域内时，视为表格单元格文字。"""
    center = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    return any(fitz.Rect(table).contains(center) for table in table_bboxes)
