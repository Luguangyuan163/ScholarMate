"""Europe PMC 适配器测试：年份查询语法、作者拆分与 PDF 地址回退。"""

from __future__ import annotations

from app.services.europepmc_service import (
    EuropePmcService,
    _parse_europepmc_response,
    build_query,
)

EUROPEPMC_JSON = {
    "resultList": {
        "result": [
            {
                "id": "33301246",
                "source": "MED",
                "pmid": "33301246",
                "pmcid": "PMC7744924",
                "doi": "10.1000/XYZ.1",
                "title": "Deep learning for veterinary imaging",
                "authorString": "Zhang L, Wang H, Smith J.",
                "journalTitle": "Vet Radiol",
                "pubYear": "2025",
                "abstractText": "We study deep learning on animal CT scans.",
                "citedByCount": 12,
                "fullTextUrlList": {
                    "fullTextUrl": [
                        {
                            "documentStyle": "html",
                            "site": "Europe_PMC",
                            "url": "https://europepmc.org/article/PMC/PMC7744924",
                        }
                    ]
                },
            }
        ]
    }
}


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.last_url = None
        self.last_params = None

    async def get(self, url, params=None, headers=None):
        self.last_url = url
        self.last_params = params
        return FakeResponse(self._payload)


def test_build_query_without_year():
    assert build_query("deep learning", None, None) == "deep learning"


def test_build_query_with_year_range():
    query = build_query("deep learning", 2024, 2026)
    assert "FIRST_PDATE:[2024-01-01 TO 2026-12-31]" in query
    assert query.startswith("(deep learning)")


def test_parse_europepmc_response_maps_fields():
    items = _parse_europepmc_response(EUROPEPMC_JSON)
    assert len(items) == 1
    item = items[0]
    assert item.source == "europepmc"
    assert item.title == "Deep learning for veterinary imaging"
    assert item.authors == ["Zhang L", "Wang H", "Smith J"]
    assert item.year == 2025
    assert item.citation_count == 12
    assert item.external_id == "10.1000/XYZ.1"
    assert item.url == "https://doi.org/10.1000/XYZ.1"
    assert item.pdf_url == "https://europepmc.org/articles/PMC7744924?pdf=render"


def test_parse_europepmc_prefers_explicit_pdf_url():
    payload = {
        "resultList": {
            "result": [
                {
                    "id": "1",
                    "title": "Open access paper",
                    "fullTextUrlList": {
                        "fullTextUrl": [
                            {
                                "documentStyle": "pdf",
                                "url": "https://example.org/open.pdf",
                            }
                        ]
                    },
                }
            ]
        }
    }
    items = _parse_europepmc_response(payload)
    assert items[0].pdf_url == "https://example.org/open.pdf"


def test_parse_europepmc_without_doi_uses_article_url():
    payload = {
        "resultList": {
            "result": [{"id": "999", "source": "MED", "title": "No DOI paper"}]
        }
    }
    items = _parse_europepmc_response(payload)
    assert items[0].external_id == "999"
    assert items[0].url == "https://europepmc.org/article/MED/999"
    assert items[0].pdf_url == ""


async def test_search_sends_query_format_and_page_size():
    client = FakeClient(EUROPEPMC_JSON)
    service = EuropePmcService(client=client)
    items = await service.search("veterinary", limit=5, year_from=2025, year_to=2025)
    assert items[0].title == "Deep learning for veterinary imaging"
    assert client.last_params["format"] == "json"
    assert client.last_params["pageSize"] == 5
    assert client.last_params["resultType"] == "core"
    assert "FIRST_PDATE:[2025-01-01 TO 2025-12-31]" in client.last_params["query"]
