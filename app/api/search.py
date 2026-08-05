"""搜索接口：arXiv 主源 + S2 回退 + 24h 缓存 + 本地语义检索。"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from app.schemas.search import PaperItem, SearchRequest, SearchResponse
from app.services.arxiv_service import ArxivService
from app.services.cache_service import SearchCacheStore
from app.services.openalex_service import OpenAlexService
from app.services.semantic_scholar_service import SemanticScholarService
from app.services.vector_store_service import VectorHit, VectorStoreService

router = APIRouter(prefix="/api/search", tags=["search"])


def _get_arxiv_service(request: Request) -> ArxivService:
    return request.app.state.arxiv_service


def _get_s2_service(request: Request) -> SemanticScholarService:
    return request.app.state.s2_service


def _get_openalex_service(request: Request) -> OpenAlexService:
    return request.app.state.openalex_service


def _get_cache_store(request: Request) -> SearchCacheStore:
    return SearchCacheStore(request.app.state.database)


@router.post("")
async def search_papers(
    request: Request,
    payload: SearchRequest,
    arxiv: Annotated[ArxivService, Depends(_get_arxiv_service)],
    s2: Annotated[SemanticScholarService, Depends(_get_s2_service)],
    openalex: Annotated[OpenAlexService, Depends(_get_openalex_service)],
    cache: Annotated[SearchCacheStore, Depends(_get_cache_store)],
) -> Response:
    if payload.source not in ("arxiv", "s2", "local"):
        raise HTTPException(status_code=501, detail=f"数据源 {payload.source} 尚未实现")

    if payload.source == "local":
        items = await _search_local(request, payload)
        return _respond(request, payload, items, "local")

    cache_key = SearchCacheStore.build_key(
        payload.source, payload.query, payload.max_results, payload.year_from, payload.year_to
    )
    cached = await cache.get(cache_key)
    if cached is not None:
        items, used_source = cached, payload.source
    else:
        try:
            items, used_source = await _fetch(payload, arxiv, s2, openalex)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="检索服务暂时不可达，请稍后重试") from exc
        await cache.set(cache_key, items)
    return _respond(request, payload, items, used_source)


async def _fetch(
    payload: SearchRequest,
    arxiv: ArxivService,
    s2: SemanticScholarService,
    openalex: OpenAlexService,
) -> tuple[list[PaperItem], str]:
    if payload.source == "s2":
        return await _search_metadata(s2, openalex, payload)
    try:
        items = await arxiv.search(
            payload.query,
            max_results=payload.max_results,
            year_from=payload.year_from,
            year_to=payload.year_to,
        )
        return items, "arxiv"
    except httpx.HTTPError:
        return await _search_metadata(s2, openalex, payload)


async def _search_metadata(
    s2: SemanticScholarService,
    openalex: OpenAlexService,
    payload: SearchRequest,
) -> tuple[list[PaperItem], str]:
    """优先 S2，失败（如无 key 被限流）时回退 OpenAlex。"""
    try:
        items = await s2.search(
            payload.query,
            limit=payload.max_results,
            year_from=payload.year_from,
            year_to=payload.year_to,
        )
        return items, "s2"
    except httpx.HTTPError:
        items = await openalex.search(
            payload.query,
            limit=payload.max_results,
            year_from=payload.year_from,
            year_to=payload.year_to,
        )
        return items, "openalex"


async def _search_local(
    request: Request, payload: SearchRequest
) -> list[PaperItem]:
    embedding_service = request.app.state.embedding_service
    vector_store: VectorStoreService = request.app.state.vector_store
    query_vectors = await embedding_service.embed_texts([payload.query])
    hits = await run_in_threadpool(
        vector_store.search, query_vectors[0], payload.max_results
    )
    return [_hit_to_paper(hit) for hit in hits]


def _hit_to_paper(hit: VectorHit) -> PaperItem:
    return PaperItem(
        title=hit.name,
        abstract=hit.document,
        source="local",
        external_id=str(hit.pdf_id),
        url="",
    )


def _respond(
    request: Request,
    payload: SearchRequest,
    items: list[PaperItem],
    used_source: str,
) -> Response:
    if request.headers.get("HX-Request") == "true":
        template = request.app.state.templates.get_template("partials/search_results.html")
        return HTMLResponse(template.render(items=items, query=payload.query))
    return SearchResponse(
        query=payload.query, source=used_source, items=items, total=len(items)
    )
