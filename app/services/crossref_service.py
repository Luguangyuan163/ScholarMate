"""Crossref 来源适配器：期刊与会议论文的 DOI 权威元数据。"""

from __future__ import annotations

import re

import httpx

from app.schemas.search import PaperItem
from app.services.http_throttle import ThrottledJsonClient
from app.services.paper_source import NotSupportedError

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
MIN_REQUEST_INTERVAL_SECONDS = 0.2  # 带 mailto 进礼貌池（建议 ≤5 rps）
DEFAULT_ROWS = 10
SELECT_FIELDS = (
    "DOI,title,abstract,author,issued,is-referenced-by-count,URL,link,container-title"
)
JATS_TAG_PATTERN = re.compile(r"<[^>]+>")
PDF_CONTENT_TYPE = "application/pdf"


class CrossrefService:
    """Crossref `/works` 检索。"""

    name = "crossref"
    domains: tuple[str, ...] = ("general", "journal")

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        mailto: str = "",
        min_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self._http = ThrottledJsonClient(client=client, min_interval=min_interval)
        self._mailto = mailto

    async def search(
        self,
        query: str,
        limit: int = DEFAULT_ROWS,
        *,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[PaperItem]:
        params: dict = {"query": query, "rows": limit, "select": SELECT_FIELDS}
        if self._mailto:
            params["mailto"] = self._mailto
        filters = _date_filters(year_from, year_to)
        if filters:
            params["filter"] = ",".join(filters)
        data = await self._http.get_json(CROSSREF_WORKS_URL, params=params)
        return _parse_crossref_response(data)

    async def expand(self, external_id: str, kind: str) -> list[PaperItem]:
        raise NotSupportedError("Crossref 暂不提供引用关系扩展")


def _date_filters(year_from: int | None, year_to: int | None) -> list[str]:
    filters = []
    if year_from is not None:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if year_to is not None:
        filters.append(f"until-pub-date:{year_to}-12-31")
    return filters


def _parse_crossref_response(data: dict) -> list[PaperItem]:
    works = (data.get("message") or {}).get("items") or []
    items = [_parse_work(work) for work in works]
    return [item for item in items if item.title]


def _parse_work(work: dict) -> PaperItem:
    return PaperItem(
        title=_strip_tags(_first(work.get("title"))),
        authors=_parse_authors(work.get("author") or []),
        abstract=_strip_tags(work.get("abstract") or "").strip(),
        source="crossref",
        external_id=work.get("DOI", ""),
        year=_parse_year(work.get("issued")),
        citation_count=int(work.get("is-referenced-by-count") or 0),
        url=work.get("URL", ""),
        pdf_url=_parse_pdf_url(work.get("link") or []),
    )


def _first(value) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value) if value else ""


def _parse_authors(authors: list) -> list[str]:
    names = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        family = author.get("family", "")
        given = author.get("given", "")
        full = " ".join(part for part in (given, family) if part).strip()
        if full:
            names.append(full)
    return names


def _parse_year(issued) -> int | None:
    if not isinstance(issued, dict):
        return None
    date_parts = issued.get("date-parts") or []
    if not date_parts or not date_parts[0]:
        return None
    year = date_parts[0][0]
    return int(year) if isinstance(year, int) else None


def _parse_pdf_url(links: list) -> str:
    for link in links:
        if not isinstance(link, dict):
            continue
        if link.get("content-type") == PDF_CONTENT_TYPE and link.get("URL"):
            return str(link["URL"])
    return ""


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", JATS_TAG_PATTERN.sub(" ", text)).strip()
