"""OpenAlex API 封装：免 key 元数据源，提供论文检索、详情与引用量（cited_by_count）。"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.schemas.search import PaperItem

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
USER_AGENT = "ScholarMate/0.1 (graduation project)"
REQUEST_TIMEOUT_SECONDS = 30.0
MIN_REQUEST_INTERVAL_SECONDS = 0.2  # 带 mailto 进入礼貌池（10 rps），留安全余量


def _is_transient(exc: BaseException) -> bool:
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in (429, 500, 502, 503)
    )


class OpenAlexService:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        mailto: str = "",
        min_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self._mailto = mailto
        self._min_interval = min_interval
        self._last_request_at = 0.0
        self._lock = asyncio.Lock()

    async def search(
        self,
        query: str,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[PaperItem]:
        params = {"search": query, "per-page": limit}
        if self._mailto:
            params["mailto"] = self._mailto
        if year_from is not None or year_to is not None:
            params["filter"] = _year_filter(year_from, year_to)
        response = await self._get(OPENALEX_WORKS_URL, params=params)
        return _parse_openalex_response(response.json())

    async def get_paper_detail(self, paper_id: str) -> dict:
        """返回与 S2 兼容的归一化详情（title/abstract/year/citationCount/url）。"""
        params = {"mailto": self._mailto} if self._mailto else {}
        response = await self._get(
            f"{OPENALEX_WORKS_URL}/{quote(paper_id, safe='')}",
            params=params,
        )
        return _normalize_detail(response.json())

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _get(self, url: str, params: dict) -> httpx.Response:
        async with self._lock:
            await self._throttle()
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_interval - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_at = time.monotonic()


def _parse_openalex_response(data: dict) -> list[PaperItem]:
    items = []
    for work in data.get("results", []):
        openalex_id = str(work.get("id", "")).rsplit("/", 1)[-1]
        authors = [
            author["author"]["display_name"]
            for author in work.get("authorships", [])
            if author.get("author", {}).get("display_name")
        ]
        best_oa = work.get("best_oa_location") or {}
        oa_url = (work.get("open_access") or {}).get("oa_url", "") or ""
        items.append(
            PaperItem(
                title=work.get("title", ""),
                authors=authors,
                abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
                source="openalex",
                external_id=openalex_id,
                year=work.get("publication_year"),
                citation_count=work.get("cited_by_count", 0),
                url=work.get("doi") or work.get("id", ""),
                pdf_url=best_oa.get("pdf_url", "")
                or (oa_url if oa_url.lower().endswith(".pdf") else ""),
            )
        )
    return items


def _normalize_detail(work: dict) -> dict:
    return {
        "paperId": str(work.get("id", "")).rsplit("/", 1)[-1],
        "title": work.get("title", ""),
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "year": work.get("publication_year"),
        "citationCount": work.get("cited_by_count", 0),
        "url": work.get("doi") or work.get("id", ""),
    }


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """将 OpenAlex 的倒排索引重建为原文顺序。"""
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        for index in indexes:
            positions[index] = word
    return " ".join(positions[i] for i in sorted(positions))


def _year_filter(year_from: int | None, year_to: int | None) -> str:
    start = year_from if year_from is not None else year_to
    end = year_to if year_to is not None else year_from
    if start is not None and end is not None and start != end:
        return f"publication_year:{start}-{end}"
    return f"publication_year:{start if start is not None else end}"
