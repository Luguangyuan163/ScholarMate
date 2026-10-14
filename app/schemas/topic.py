"""主题管理与论文实体的请求 / 响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=191)
    description: str = ""
    keywords: list[str] = []
    color: str = ""


class TopicUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=191)
    description: str | None = None
    keywords: list[str] | None = None
    color: str | None = None
    archived: bool | None = None


class TopicOut(BaseModel):
    id: int
    name: str
    description: str = ""
    keywords: list[str] = []
    color: str = ""
    archived: bool = False
    paper_count: int = 0


class TopicMergeRequest(BaseModel):
    target_id: int


class TopicPapersRequest(BaseModel):
    paper_ids: list[int] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class PaperOut(BaseModel):
    """论文实体（知识库中的论文，与本地 PDF 论文库不同）。"""

    id: int
    title: str
    authors: list[str] = []
    year: int | None = None
    venue: str = ""
    citation_count: int = 0
    sources: list[str] = []
    doi: str | None = None
    abstract: str = ""
    url: str = ""
    pdf_url: str = ""
    topics: list[TopicOut] = []


class PaperListOut(BaseModel):
    total: int
    items: list[PaperOut] = []


class ClassifySuggestion(BaseModel):
    topic_id: int
    name: str
    matched_keywords: list[str] = []
    confidence: float = 0.0
