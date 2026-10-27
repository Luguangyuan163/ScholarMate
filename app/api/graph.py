"""知识图谱接口：单次检索图谱、历史综合图谱与按需扩展。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.schemas.graph import GraphExpandRequest, GraphOut
from app.services.graph_service import MAX_GLOBAL_NODES, GraphService

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _service(request: Request) -> GraphService:
    return GraphService(
        request.app.state.database,
        openalex=request.app.state.openalex_service,
    )


@router.get("/session/{session_id}")
async def session_graph(request: Request, session_id: int) -> GraphOut:
    graph = await _service(request).session_graph(session_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="检索会话不存在")
    return graph


@router.get("/global")
async def global_graph(
    request: Request,
    topic_id: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    source: str | None = None,
    min_citations: int = 0,
    limit: int = MAX_GLOBAL_NODES,
) -> GraphOut:
    return await _service(request).global_graph(
        topic_id=topic_id,
        year_from=year_from,
        year_to=year_to,
        source=source,
        min_citations=max(min_citations, 0),
        limit=limit,
    )


@router.post("/expand")
async def expand_graph(request: Request, payload: GraphExpandRequest) -> dict:
    result = await _service(request).expand(payload.paper_id, payload.kinds)
    if result is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return result
