"""论文实体接口：知识库论文的列表、详情与分类建议。

与 `/api/papers`（本地 PDF 论文库）区分：这里操作的是跨来源归一后的
论文实体，也就是知识图谱的节点。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.mappers import match_out, paper_out, topic_out
from app.schemas.topic import ClassifySuggestion, PaperListOut, PaperOut
from app.services.paper_store import PaperStore
from app.services.topic_service import TopicStore

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _papers(request: Request) -> PaperStore:
    return PaperStore(request.app.state.database)


def _topics(request: Request) -> TopicStore:
    return TopicStore(request.app.state.database)


@router.get("/papers")
async def list_papers(
    request: Request,
    topic_id: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    source: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> PaperListOut:
    total, papers = await _papers(request).list_papers(
        topic_id=topic_id,
        year_from=year_from,
        year_to=year_to,
        source=source,
        query=q,
        limit=max(1, min(limit, 200)),
        offset=max(offset, 0),
    )
    topics = _topics(request)
    items = [
        paper_out(
            paper,
            [topic_out(summary) for summary in await topics.topics_for_paper(paper.id)],
        )
        for paper in papers
    ]
    return PaperListOut(total=total, items=items)


@router.get("/papers/{paper_id}")
async def get_paper(request: Request, paper_id: int) -> PaperOut:
    paper = await _papers(request).get_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    summaries = await _topics(request).topics_for_paper(paper_id)
    return paper_out(paper, [topic_out(summary) for summary in summaries])


@router.post("/papers/{paper_id}/classify")
async def classify_paper(request: Request, paper_id: int) -> list[ClassifySuggestion]:
    """按主题关键词规则给出候选主题（把标题当作待匹配文本）。"""
    paper = await _papers(request).get_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    matches = await _topics(request).classify_keywords([paper.title])
    return [ClassifySuggestion(**match_out(match)) for match in matches]
