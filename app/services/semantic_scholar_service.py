"""Semantic Scholar API 封装：论文检索与引用量（citationCount）。"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.schemas.search import PaperItem

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,authors.name,year,citationCount,externalIds,url"
USER_AGENT = "ScholarMate/0.1 (graduation project)"
REQUEST_TIMEOUT_SECONDS = 30.0
MIN_REQUEST_INTERVAL_SECONDS = 1.0  # 无 key 共享限流约 100 次/5 分钟，留安全间隔


def _is_rate_limited(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429


class SemanticScholarService:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        api_key: str = "",
        min_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self._api_key = api_key
        self._min_interval = min_interval
        self._last_request_at = 0.0
        self._lock = asyncio.Lock()

    async def search(self, query: str, limit: int = 10) -> list[PaperItem]:
        params = {"query": query, "limit": limit, "fields": S2_FIELDS}
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        response = await self._get(S2_SEARCH_URL, params=params, headers=headers)
        return _parse_s2_response(response.json())

    async def get_paper_detail(self, paper_id: str) -> dict:
        params = {"fields": S2_FIELDS}
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        response = await self._get(
            f"{S2_SEARCH_URL.rsplit('/paper', 1)[0]}/paper/{quote(paper_id, safe='')}",
            params=params,
            headers=headers,
        )
        return response.json()

    @retry(
        retry=retry_if_exception(_is_rate_limited),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _get(self, url: str, params: dict, headers: dict) -> httpx.Response:
        async with self._lock:
            await self._throttle()
            response = await self._client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_interval - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_at = time.monotonic()


def _parse_s2_response(data: dict) -> list[PaperItem]:
    items = []
    for paper in data.get("data", []):
        authors = [a.get("name", "") for a in paper.get("authors", []) if a.get("name")]
        external_ids = paper.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv", "")
        items.append(
            PaperItem(
                title=paper.get("title", ""),
                authors=authors,
                abstract=paper.get("abstract") or "",
                source="s2",
                external_id=arxiv_id or paper.get("paperId", ""),
                year=paper.get("year"),
                citation_count=paper.get("citationCount", 0),
                url=paper.get("url", ""),
            )
        )
    return items
