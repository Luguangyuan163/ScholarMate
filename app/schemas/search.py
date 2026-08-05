"""搜索接口的请求与响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    source: str = "arxiv"  # arxiv | s2 | local
    max_results: int = Field(default=10, ge=1, le=50)
    year_from: int | None = Field(default=None, ge=1991, le=2100)
    year_to: int | None = Field(default=None, ge=1991, le=2100)


class PaperItem(BaseModel):
    title: str
    authors: list[str] = []
    abstract: str = ""
    source: str
    external_id: str
    year: int | None = None
    citation_count: int = 0
    url: str = ""
    pdf_url: str = ""


class SearchResponse(BaseModel):
    query: str
    source: str
    items: list[PaperItem]
    total: int
