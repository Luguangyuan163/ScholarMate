"""搜索接口：arXiv 为主数据源，HTMX 请求返回 HTML 局部片段。"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.schemas.search import SearchRequest, SearchResponse
from app.services.arxiv_service import ArxivService

router = APIRouter(prefix="/api/search", tags=["search"])


def _get_arxiv_service(request: Request) -> ArxivService:
    return request.app.state.arxiv_service


@router.post("")
async def search_papers(
    request: Request,
    payload: SearchRequest,
    arxiv: Annotated[ArxivService, Depends(_get_arxiv_service)],
) -> Response:
    if payload.source != "arxiv":
        raise HTTPException(status_code=501, detail=f"数据源 {payload.source} 尚未实现")
    try:
        items = await arxiv.search(
            payload.query,
            max_results=payload.max_results,
            year_from=payload.year_from,
            year_to=payload.year_to,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="arXiv API 暂时不可达，请稍后重试"
        ) from exc
    if request.headers.get("HX-Request") == "true":
        template = request.app.state.templates.get_template("partials/search_results.html")
        return HTMLResponse(template.render(items=items, query=payload.query))
    return SearchResponse(query=payload.query, source="arxiv", items=items, total=len(items))
