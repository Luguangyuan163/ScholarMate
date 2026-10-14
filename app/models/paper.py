"""论文实体、主题、检索会话与知识图谱边模型。

对应设计文档 `docs/ScholarMate-知识图谱设计.md` 第 8 节。论文实体是全系统
的归一对象：同一篇论文无论来自 arXiv、Semantic Scholar 还是 Crossref，都只
在 `papers` 表里保留一行，多来源通过 `sources_json` 累加。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import utcnow


class Paper(Base):
    """跨来源归一后的论文实体。"""

    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(primary_key=True)
    doi: Mapped[str | None] = mapped_column(String(191), unique=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(64), index=True)
    s2_id: Mapped[str | None] = mapped_column(String(64), index=True)
    openalex_id: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    normalized_title: Mapped[str] = mapped_column(Text, default="")
    # 标题指纹：归一化标题 + 首作者 + 年份的 SHA1，用于缺少 DOI 时的去重
    fingerprint: Mapped[str] = mapped_column(String(40), index=True)
    abstract: Mapped[str] = mapped_column(Text, default="")
    authors_json: Mapped[str] = mapped_column(Text, default="[]")
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str] = mapped_column(String(255), default="")
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    url: Mapped[str] = mapped_column(String(512), default="")
    pdf_url: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Topic(Base):
    """用户可管理的论文主题（分类单元）。"""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(191), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    color: Mapped[str] = mapped_column(String(16), default="#1f3a5f")
    archived: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaperTopic(Base):
    """论文与主题的归属关系。"""

    __tablename__ = "paper_topics"

    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    # user（用户指定）| keyword（关键词规则）| llm（模型建议）
    assigned_by: Mapped[str] = mapped_column(String(16), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchSession(Base):
    """一次多关键词检索会话。"""

    __tablename__ = "search_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    year_from: Mapped[int | None] = mapped_column(Integer)
    year_to: Mapped[int | None] = mapped_column(Integer)
    # running | done | failed
    status: Mapped[str] = mapped_column(String(16), default="done")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_sources: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchSessionPaper(Base):
    """检索会话与论文的关联（单次检索图谱的范围来源）。"""

    __tablename__ = "search_session_papers"

    session_id: Mapped[int] = mapped_column(
        ForeignKey("search_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    matched_keywords_json: Mapped[str] = mapped_column(Text, default="[]")


class PaperEdge(Base):
    """论文之间的边：引用关系与相似关系。"""

    __tablename__ = "paper_edges"
    __table_args__ = (
        UniqueConstraint(
            "src_paper_id", "dst_paper_id", "edge_type", name="uq_paper_edge"
        ),
        Index("ix_paper_edges_src", "src_paper_id", "edge_type"),
        Index("ix_paper_edges_dst", "dst_paper_id", "edge_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    src_paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE")
    )
    dst_paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE")
    )
    # cites | similar
    edge_type: Mapped[str] = mapped_column(String(16))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
