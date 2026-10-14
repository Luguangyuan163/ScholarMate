"""DOAJ 来源适配器：开放获取期刊论文。

选它替换 DBLP 的原因见设计文档 4.1 节：DBLP 已启用反爬（Anubis）挑战，
程序化请求返回 202 + 挑战页，无法稳定接入。
"""

from __future__ import annotations

from urllib.parse import quote

import httpx

from app.schemas.search import PaperItem
from app.services.http_throttle import ThrottledJsonClient
from app.services.paper_source import NotSupportedError

DOAJ_SEARCH_URL = "https://doaj.org/api/search/articles/{query}"
MIN_REQUEST_INTERVAL_SECONDS = 0.5
DEFAULT_PAGE_SIZE = 10
ABSTRACT_LABEL_PREFIXES = ("abstract", "summary")


class DoajService:
    """DOAJ 文章检索。"""

    name = "doaj"
    domains: tuple[str, ...] = ("open-access", "journal")

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        min_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self._http = ThrottledJsonClient(client=client, min_interval=min_interval)

    async def search(
        self,
        query: str,
        limit: int = DEFAULT_PAGE_SIZE,
        *,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[PaperItem]:
        url = DOAJ_SEARCH_URL.format(query=quote(build_query(query, year_from, year_to)))
        data = await self._http.get_json(url, params={"pageSize": limit})
        return _parse_doaj_response(data)

    async def expand(self, external_id: str, kind: str) -> list[PaperItem]:
        raise NotSupportedError("DOAJ 暂不提供引用关系扩展")


def build_query(query: str, year_from: int | None, year_to: int | None) -> str:
    """DOAJ 用 Lucene 风格语法表达字段与范围。"""
    if year_from is None and year_to is None:
        return query
    start = year_from if year_from is not None else 1800
    end = year_to if year_to is not None else 2100
    return f"({query}) AND bibjson.year:[{start} TO {end}]"


def _parse_doaj_response(data: dict) -> list[PaperItem]:
    results = data.get("results") or []
    items = [_parse_article(entry) for entry in results]
    return [item for item in items if item.title]


def _parse_article(entry: dict) -> PaperItem:
    bib = entry.get("bibjson") or {}
    doi = _identifier(bib, "doi")
    links = bib.get("link") or []
    return PaperItem(
        title=str(bib.get("title") or "").strip(),
        authors=_parse_authors(bib.get("author") or []),
        abstract=_strip_abstract_label(str(bib.get("abstract") or "").strip()),
        source="doaj",
        external_id=doi or str(entry.get("id") or ""),
        year=_parse_year(bib.get("year")),
        citation_count=0,
        url=f"https://doi.org/{doi}" if doi else _fulltext_url(links),
        pdf_url=_pdf_url(links),
    )


def _identifier(bib: dict, kind: str) -> str:
    for entry in bib.get("identifier") or []:
        if isinstance(entry, dict) and entry.get("type") == kind and entry.get("id"):
            return str(entry["id"]).strip()
    return ""


def _parse_authors(authors: list) -> list[str]:
    names = []
    for author in authors:
        if isinstance(author, dict) and author.get("name"):
            names.append(str(author["name"]).strip())
    return names


def _fulltext_url(links: list) -> str:
    for link in links:
        if isinstance(link, dict) and link.get("type") == "fulltext" and link.get("url"):
            return str(link["url"])
    return ""


def _pdf_url(links: list) -> str:
    for link in links:
        if not isinstance(link, dict):
            continue
        if str(link.get("content_type", "")).upper() == "PDF" and link.get("url"):
            return str(link["url"])
    return ""


def _parse_year(value) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _strip_abstract_label(text: str) -> str:
    lowered = text.lower()
    for label in ABSTRACT_LABEL_PREFIXES:
        if lowered.startswith(label):
            return text[len(label) :].lstrip(":： ").strip()
    return text
