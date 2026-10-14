"""主题管理接口：主题 CRUD、合并、论文归属。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.mappers import paper_out, topic_out
from app.schemas.topic import (
    PaperListOut,
    TopicCreate,
    TopicMergeRequest,
    TopicOut,
    TopicPapersRequest,
    TopicUpdate,
)
from app.services.paper_store import PaperStore
from app.services.topic_service import TopicStore

router = APIRouter(prefix="/api/topics", tags=["topics"])


def _topics(request: Request) -> TopicStore:
    return TopicStore(request.app.state.database)


def _papers(request: Request) -> PaperStore:
    return PaperStore(request.app.state.database)


@router.get("")
async def list_topics(request: Request, include_archived: bool = False) -> list[TopicOut]:
    summaries = await _topics(request).list_topics(include_archived=include_archived)
    return [topic_out(summary) for summary in summaries]


@router.post("", status_code=201)
async def create_topic(request: Request, payload: TopicCreate) -> TopicOut:
    store = _topics(request)
    existing = await store.list_topics(include_archived=True)
    if any(summary.name == payload.name.strip() for summary in existing):
        raise HTTPException(status_code=409, detail="同名主题已存在")
    topic = await store.create(
        name=payload.name,
        description=payload.description,
        keywords=payload.keywords,
        color=payload.color,
    )
    return TopicOut(
        id=topic.id,
        name=topic.name,
        description=topic.description or "",
        keywords=payload.keywords,
        color=topic.color or "",
        archived=False,
        paper_count=0,
    )


@router.patch("/{topic_id}")
async def update_topic(
    request: Request, topic_id: int, payload: TopicUpdate
) -> TopicOut:
    store = _topics(request)
    topic = await store.update(
        topic_id,
        name=payload.name,
        description=payload.description,
        keywords=payload.keywords,
        color=payload.color,
        archived=payload.archived,
    )
    if topic is None:
        raise HTTPException(status_code=404, detail="主题不存在")
    for summary in await store.list_topics(include_archived=True):
        if summary.id == topic_id:
            return topic_out(summary)
    raise HTTPException(status_code=404, detail="主题不存在")


@router.delete("/{topic_id}")
async def delete_topic(request: Request, topic_id: int) -> dict:
    deleted = await _topics(request).delete(topic_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="主题不存在")
    return {"deleted": topic_id}


@router.post("/{topic_id}/merge")
async def merge_topic(
    request: Request, topic_id: int, payload: TopicMergeRequest
) -> dict:
    store = _topics(request)
    if await store.get(topic_id) is None or await store.get(payload.target_id) is None:
        raise HTTPException(status_code=404, detail="主题不存在")
    moved = await store.merge(topic_id, payload.target_id)
    return {"moved": moved, "target_id": payload.target_id}


@router.post("/{topic_id}/papers")
async def assign_papers(
    request: Request, topic_id: int, payload: TopicPapersRequest
) -> dict:
    store = _topics(request)
    if await store.get(topic_id) is None:
        raise HTTPException(status_code=404, detail="主题不存在")
    assigned = await store.assign_papers(
        topic_id, payload.paper_ids, confidence=payload.confidence
    )
    return {"assigned": assigned}


@router.delete("/{topic_id}/papers")
async def remove_papers(
    request: Request, topic_id: int, payload: TopicPapersRequest
) -> dict:
    removed = await _topics(request).remove_papers(topic_id, payload.paper_ids)
    return {"removed": removed}


@router.get("/{topic_id}/papers")
async def topic_papers(
    request: Request,
    topic_id: int,
    limit: int = 50,
    offset: int = 0,
) -> PaperListOut:
    store = _topics(request)
    if await store.get(topic_id) is None:
        raise HTTPException(status_code=404, detail="主题不存在")
    papers = await store.papers_for_topic(topic_id, limit=limit, offset=offset)
    items = [
        paper_out(paper, [topic_out(summary) for summary in await store.topics_for_paper(paper.id)])
        for paper in papers
    ]
    return PaperListOut(total=len(items), items=items)
