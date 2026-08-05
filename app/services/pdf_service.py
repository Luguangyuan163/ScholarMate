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


@dataclass
class LayoutParagraph:
    """带坐标的排版段落，用于版面对照翻译。"""

    page: int
    page_width: float
    page_height: float
    bbox: tuple[float, float, float, float]
    text: str
    font_size: float
    bold: bool = False


@dataclass
class PageLayout:
    """单页排版信息：页面尺寸 + 按阅读顺序排列的段落。"""

    page: int
    width: float
    height: float
    paragraphs: list[LayoutParagraph]


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

    def extract_layout(self, pdf_path: str) -> list[PageLayout]:
        """提取带坐标的排版段落（剔除图表文字），供版面对照翻译使用。

        每个段落携带页号、页面尺寸、bbox（PDF 点坐标）与字号；
        前端据此把译文按原坐标渲染成与原 PDF 一致的版面。
        """
        with fitz.open(pdf_path) as doc:
            layouts: list[PageLayout] = []
            for page_index, page in enumerate(doc):
                image_bboxes = [
                    fitz.Rect(info["bbox"]) for info in page.get_image_info()
                ]
                table_bboxes = [
                    fitz.Rect(table.bbox) for table in page.find_tables().tables
                ]
                blocks: list[dict] = []
                for block in page.get_text("dict")["blocks"]:
                    if block.get("type") != 0:
                        continue
                    kept_lines: list[dict] = []
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        if not spans:
                            continue
                        rect = fitz.Rect(line["bbox"])
                        if _overlaps_image(rect, image_bboxes) or _inside_table(
                            rect, table_bboxes
                        ):
                            continue
                        text = _normalize_text(_line_text(spans)).strip()
                        if not text:
                            continue
                        kept_lines.append(
                            {
                                "bbox": rect,
                                "text": text,
                                "size": max(round(s["size"], 2) for s in spans),
                                "bold": any(
                                    (s.get("flags", 0) & 16) and s["text"].strip()
                                    for s in spans
                                ),
                            }
                        )
                    if not kept_lines:
                        continue
                    bbox = fitz.Rect(kept_lines[0]["bbox"])
                    for line in kept_lines[1:]:
                        bbox |= fitz.Rect(line["bbox"])
                    blocks.append(
                        {
                            "bbox": (bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                            "text": " ".join(line["text"] for line in kept_lines),
                            "size": max(line["size"] for line in kept_lines),
                            "bold": any(line["bold"] for line in kept_lines),
                        }
                    )
                if not blocks:
                    continue
                ordered = _order_blocks(blocks, page.rect.width)
                merged = _merge_paragraphs(ordered)
                paragraphs = [
                    LayoutParagraph(
                        page=page_index + 1,
                        page_width=page.rect.width,
                        page_height=page.rect.height,
                        bbox=item["bbox"],
                        text=item["text"],
                        font_size=item["size"],
                        bold=item["bold"],
                    )
                    for item in merged
                ]
                layouts.append(
                    PageLayout(
                        page=page_index + 1,
                        width=page.rect.width,
                        height=page.rect.height,
                        paragraphs=paragraphs,
                    )
                )
            return layouts

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


def fit_font_size(
    text: str, font_size: float, bbox_width: float, bbox_height: float | None = None
) -> float:
    """按译文长度与段落框尺寸估算合适的展示字号。

    允许译文行数最多达到原文行数的 2.2 倍（中文比英文密，行数翻倍属正常），
    仅当明显超出时才缩字号，下限为原字号的 0.7，避免长段落被压到不可读。
    """
    if bbox_width <= 0 or font_size <= 0:
        return font_size
    estimated_pt = _text_width_em(text) * font_size
    if estimated_pt <= bbox_width:
        return font_size
    if bbox_height and bbox_height > 0:
        line_height = font_size * 1.35
        source_lines = max(1.0, bbox_height / line_height)
        target_lines = max(1.0, source_lines * 2.2)
        needed_lines = max(1.0, estimated_pt / bbox_width)
        if needed_lines <= target_lines:
            return font_size
        fitted = font_size * (target_lines * bbox_width) / estimated_pt
        return max(font_size * 0.7, fitted)
    fitted = font_size * bbox_width / estimated_pt
    return max(font_size * 0.7, fitted)


def _normalize_text(text: str) -> str:
    """NFKC 规范化：分解 PDF 连字（ﬁ→fi 等），统一兼容字符。"""
    return unicodedata.normalize("NFKC", text)


def _line_text(spans: list[dict]) -> str:
    """拼接一行内的 span 文本，跨 span 间隙较大时补空格。"""
    parts: list[str] = []
    prev_end: float | None = None
    prev_size: float | None = None
    for span in spans:
        text = span.get("text", "")
        if not text:
            continue
        if prev_end is not None and prev_size is not None:
            gap = span["bbox"][0] - prev_end
            if (
                gap > max(2.0, 0.3 * prev_size)
                and parts
                and not parts[-1].endswith(" ")
                and not text.startswith(" ")
            ):
                parts.append(" ")
        parts.append(text)
        prev_end = span["bbox"][2]
        prev_size = max(prev_size or 0, span.get("size", 0))
    return "".join(parts)


def _order_blocks(blocks: list[dict], page_width: float) -> list[dict]:
    """按列聚类后按（列, 行）排序，正确处理双栏论文。"""
    if len(blocks) < 2:
        return blocks
    xs = sorted(block["bbox"][0] for block in blocks)
    columns: list[tuple[float, float]] = []
    current = [xs[0]]
    for x in xs[1:]:
        if x - current[-1] > max(20.0, page_width * 0.22):
            columns.append((current[0], current[-1]))
            current = [x]
        else:
            current.append(x)
    columns.append((current[0], current[-1]))

    def column_index(block: dict) -> int:
        x0 = block["bbox"][0]
        for index, (_lo, hi) in enumerate(columns):
            if x0 <= hi + 0.01:
                return index
        return len(columns) - 1

    return sorted(
        blocks,
        key=lambda block: (column_index(block), block["bbox"][1], block["bbox"][0]),
    )


def _merge_paragraphs(blocks: list[dict]) -> list[dict]:
    """保守合并同列、同字号、无缩进且间隙小的相邻块为一段，bbox 取并集。"""
    merged: list[dict] = []
    for block in blocks:
        bbox = fitz.Rect(block["bbox"])
        if merged:
            prev = merged[-1]
            prev_bbox = fitz.Rect(prev["bbox"])
            vertical_gap = bbox.y0 - prev_bbox.y1
            same_column = abs(bbox.x0 - prev_bbox.x0) <= max(4.0, 0.2 * bbox.width)
            same_size = abs(block["size"] - prev["size"]) <= 1.5
            not_indented = abs(bbox.x0 - prev_bbox.x0) <= 2.0
            if same_column and same_size and not_indented and 0 <= vertical_gap <= max(
                12.0, 1.35 * block["size"]
            ):
                prev["bbox"] = (
                    min(prev_bbox.x0, bbox.x0),
                    prev_bbox.y0,
                    max(prev_bbox.x1, bbox.x1),
                    bbox.y1,
                )
                prev["text"] = f"{prev['text']} {block['text']}"
                prev["size"] = max(prev["size"], block["size"])
                prev["bold"] = prev["bold"] or block["bold"]
                continue
        merged.append(
            {
                "bbox": (bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                "text": block["text"],
                "size": block["size"],
                "bold": block["bold"],
            }
        )
    return merged


def _text_width_em(text: str) -> float:
    """估算文本宽度（em 单位）：CJK约1.0、拉丁约0.5、空白约0.25、其他约0.7。"""
    width = 0.0
    for char in text:
        code = ord(char)
        if char.isspace():
            width += 0.25
        elif (
            (0x2E80 <= code <= 0x9FFF)
            or (0xAC00 <= code <= 0xD7AF)
            or (0xF900 <= code <= 0xFAFF)
            or (0xFF00 <= code <= 0xFFEF)
        ):
            width += 1.0
        else:
            width += 0.5
    return width


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
