"""arXiv API 封装：检索、Atom 解析、查询参数构造。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.schemas.search import PaperItem

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
USER_AGENT = "ScholarMate/0.1 (graduation project)"
REQUEST_TIMEOUT_SECONDS = 30.0


def _is_transient(exc: BaseException) -> bool:
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in (429, 500, 502, 503)
    )


class ArxivService:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def search(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[PaperItem]:
        params = _build_params(query, max_results, year_from, year_to)
        response = await self._client.get(ARXIV_API_URL, params=params)
        response.raise_for_status()
        return _parse_feed(response.text)


def _build_params(
    query: str,
    max_results: int,
    year_from: int | None,
    year_to: int | None,
) -> dict[str, Any]:
    search_query = f"all:{_sanitize(query)}"
    if year_from is not None and year_to is not None:
        search_query = (
            f"({search_query}) AND "
            f"submittedDate:[{year_from}01010000 TO {year_to}12312359]"
        )
    return {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
    }


def _sanitize(query: str) -> str:
    return " ".join(query.split())[:200]


def _parse_feed(xml_text: str) -> list[PaperItem]:
    root = ET.fromstring(xml_text)
    return [_parse_entry(entry) for entry in root.findall(f"{ATOM}entry")]


def _parse_entry(entry: ET.Element) -> PaperItem:
    title = _text(entry, f"{ATOM}title").replace("\n", " ").strip()
    summary = _text(entry, f"{ATOM}summary").replace("\n", " ").strip()
    published = _text(entry, f"{ATOM}published")
    authors = [name.text.strip() for name in entry.findall(f"{ATOM}author/{ATOM}name") if name.text]
    entry_id = _text(entry, f"{ATOM}id")
    return PaperItem(
        title=title,
        authors=authors,
        abstract=summary,
        source="arxiv",
        external_id=entry_id.rsplit("/abs/", 1)[-1],
        year=int(published[:4]) if len(published) >= 4 else None,
        citation_count=0,
        url=entry_id,
        pdf_url=f"https://arxiv.org/pdf/{entry_id.rsplit('/abs/', 1)[-1]}",
    )


def _text(element: ET.Element, path: str) -> str:
    node = element.find(path)
    return node.text or "" if node is not None else ""
