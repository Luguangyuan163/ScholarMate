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


class SearchRunRequest(BaseModel):
    """多关键词检索请求。"""

    keywords: list[str] = Field(min_length=1, max_length=8)
    sources: list[str] = ["all"]
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    per_source: int = Field(default=10, ge=1, le=50)


class MergedPaperItem(BaseModel):
    """归一去重后的论文条目。"""

    paper_id: int
    title: str
    authors: list[str] = []
    year: int | None = None
    citation_count: int = 0
    sources: list[str] = []
    matched_keywords: list[str] = []
    score: float = 0.0
    url: str = ""
    pdf_url: str = ""


class SearchRunResponse(BaseModel):
    """多关键词检索结果：保留分来源统计，便于展示来源多样性。"""

    session_id: int
    total: int
    merged: int
    by_source: dict[str, int] = {}
    failed_sources: list[str] = []
    items: list[MergedPaperItem] = []
