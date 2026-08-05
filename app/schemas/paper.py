"""论文收藏接口的请求模型。"""

from __future__ import annotations

from pydantic import BaseModel


class PaperImportItem(BaseModel):
    title: str
    authors: list[str] = []
    abstract: str = ""
    source: str
    external_id: str
    year: int | None = None
    citation_count: int = 0
    url: str = ""
    pdf_url: str = ""


class PaperImportRequest(BaseModel):
    papers: list[PaperImportItem]
