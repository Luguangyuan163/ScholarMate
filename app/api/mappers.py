"""ORM 对象到响应模型的转换。"""

from __future__ import annotations

import json

from app.models.paper import Paper
from app.schemas.topic import PaperOut, TopicOut
from app.services.topic_service import TopicMatch, TopicSummary


def topic_out(summary: TopicSummary) -> TopicOut:
    return TopicOut(
        id=summary.id,
        name=summary.name,
        description=summary.description,
        keywords=summary.keywords,
        color=summary.color,
        archived=summary.archived,
        paper_count=summary.paper_count,
    )


def match_out(match: TopicMatch) -> dict:
    return {
        "topic_id": match.topic_id,
        "name": match.name,
        "matched_keywords": match.matched_keywords,
        "confidence": match.confidence,
    }


def paper_out(paper: Paper, topics: list[TopicOut] | None = None) -> PaperOut:
    return PaperOut(
        id=paper.id,
        title=paper.title,
        authors=_json_list(paper.authors_json),
        year=paper.year,
        venue=paper.venue or "",
        citation_count=paper.citation_count or 0,
        sources=_json_list(paper.sources_json),
        doi=paper.doi,
        abstract=paper.abstract or "",
        url=paper.url or "",
        pdf_url=paper.pdf_url or "",
        topics=topics or [],
    )


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
