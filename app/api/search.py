"""搜索接口：arXiv 主数据源 + S2 回退 + 24h 缓存，HTMX 请求返回 HTML 局部片段。"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.schemas.search import PaperItem, SearchRequest, SearchResponse
from app.services.arxiv_service import ArxivService
from app.services.cache_service import SearchCacheStore
from app.services.semantic_scholar_service import SemanticScholarService

router = APIRouter(prefix="/api/search", tags=["search"])


def _get_arxiv_service(request: Request) -> ArxivService:
    return request.app.state.arxiv_service


def _get_s2_service(request: Request) -> SemanticScholarService:
    return request.app.state.s2_service


def _get_cache_store(request: Request) -> SearchCacheStore:
    return SearchCacheStore(request.app.state.database)


@router.post("")
async def search_papers(
    request: Request,
    payload: SearchRequest,
    arxiv: Annotated[ArxivService, Depends(_get_arxiv_service)],
    s2: Annotated[SemanticScholarService, Depends(_get_s2_service)],
    cache: Annotated[SearchCacheStore, Depends(_get_cache_store)],
) -> Response:
    if payload.source not in ("arxiv", "s2"):
        raise HTTPException(status_code=501, detail=f"数据源 {payload.source} 尚未实现")

    cache_key = SearchCacheStore.build_key(
        payload.source, payload.query, payload.max_results, payload.year_from, payload.year_to
    )
    cached = await cache.get(cache_key)
    if cached is not None:
        items, used_source = cached, payload.source
    else:
        try:
            items, used_source = await _fetch(payload, arxiv, s2)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="检索服务暂时不可达，请稍后重试") from exc
        await cache.set(cache_key, items)

    if request.headers.get("HX-Request") == "true":
        template = request.app.state.templates.get_template("partials/search_results.html")
        return HTMLResponse(template.render(items=items, query=payload.query))
    return SearchResponse(query=payload.query, source=used_source, items=items, total=len(items))


async def _fetch(
    payload: SearchRequest,
    arxiv: ArxivService,
    s2: SemanticScholarService,
) -> tuple[list[PaperItem], str]:
    if payload.source == "s2":
        items = await s2.search(payload.query, limit=payload.max_results)
        return items, "s2"
    try:
        items = await arxiv.search(
            payload.query,
            max_results=payload.max_results,
            year_from=payload.year_from,
            year_to=payload.year_to,
        )
        return items, "arxiv"
    except httpx.HTTPError:
        items = await s2.search(payload.query, limit=payload.max_results)
        return items, "s2"
