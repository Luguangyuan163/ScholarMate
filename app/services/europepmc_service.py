"""Europe PMC 来源适配器：生物医学与生命科学文献。"""

from __future__ import annotations

import httpx

from app.schemas.search import PaperItem
from app.services.http_throttle import ThrottledJsonClient
from app.services.paper_source import NotSupportedError

EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
MIN_REQUEST_INTERVAL_SECONDS = 0.35  # Europe PMC 建议 ≤3 rps
DEFAULT_PAGE_SIZE = 10
ARTICLE_URL_TEMPLATE = "https://europepmc.org/article/{source}/{identifier}"
PDF_URL_TEMPLATE = "https://europepmc.org/articles/{pmcid}?pdf=render"


class EuropePmcService:
    """Europe PMC 检索接口。"""

    name = "europepmc"
    domains: tuple[str, ...] = ("bio", "medical")

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
        params = {
            "query": build_query(query, year_from, year_to),
            "format": "json",
            "pageSize": limit,
            "resultType": "core",
        }
        data = await self._http.get_json(EUROPEPMC_SEARCH_URL, params=params)
        return _parse_europepmc_response(data)

    async def expand(self, external_id: str, kind: str) -> list[PaperItem]:
        raise NotSupportedError("Europe PMC 暂不提供引用关系扩展")


def build_query(query: str, year_from: int | None, year_to: int | None) -> str:
    """Europe PMC 用查询语法表达年份范围。"""
    if year_from is None and year_to is None:
        return query
    start = f"{year_from}-01-01" if year_from is not None else "1800-01-01"
    end = f"{year_to}-12-31" if year_to is not None else "2100-12-31"
    return f"({query}) AND (FIRST_PDATE:[{start} TO {end}])"


def _parse_europepmc_response(data: dict) -> list[PaperItem]:
    results = (data.get("resultList") or {}).get("result") or []
    items = [_parse_record(record) for record in results]
    return [item for item in items if item.title]


def _parse_record(record: dict) -> PaperItem:
    doi = (record.get("doi") or "").strip()
    identifier = str(record.get("id") or record.get("pmid") or "")
    source = str(record.get("source") or "MED")
    return PaperItem(
        title=(record.get("title") or "").strip(),
        authors=_split_authors(record.get("authorString") or ""),
        abstract=(record.get("abstractText") or "").strip(),
        source="europepmc",
        external_id=doi or identifier,
        year=_parse_year(record.get("pubYear")),
        citation_count=int(record.get("citedByCount") or 0),
        url=f"https://doi.org/{doi}" if doi else ARTICLE_URL_TEMPLATE.format(
            source=source, identifier=identifier
        ),
        pdf_url=_parse_pdf_url(record),
    )


def _split_authors(author_string: str) -> list[str]:
    raw = author_string.strip().rstrip(".")
    if not raw:
        return []
    return [name.strip() for name in raw.split(",") if name.strip()]


def _parse_year(value) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _parse_pdf_url(record: dict) -> str:
    urls = (record.get("fullTextUrlList") or {}).get("fullTextUrl") or []
    for entry in urls:
        if not isinstance(entry, dict):
            continue
        if entry.get("documentStyle") == "pdf" and entry.get("url"):
            return str(entry["url"])
    pmcid = str(record.get("pmcid") or "").strip()
    if pmcid:
        return PDF_URL_TEMPLATE.format(pmcid=pmcid)
    return ""
