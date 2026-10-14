"""Crossref 适配器测试：JATS 摘要清理、年份范围过滤与字段映射。"""

from __future__ import annotations

from app.services.crossref_service import CrossrefService, _parse_crossref_response

CROSSREF_JSON = {
    "message": {
        "items": [
            {
                "DOI": "10.1145/ABC.123",
                "title": ["Low-Rank Adaptation for Vision Models"],
                "abstract": "<jats:p>We propose a <jats:italic>low-rank</jats:italic> "
                "adaptation method.</jats:p>",
                "author": [
                    {"given": "Edward", "family": "Hu"},
                    {"given": "Yelong", "family": "Shen"},
                ],
                "issued": {"date-parts": [[2024, 5, 1]]},
                "is-referenced-by-count": 37,
                "URL": "https://doi.org/10.1145/abc.123",
                "container-title": ["Journal of Vision"],
                "link": [
                    {"URL": "https://example.org/landing", "content-type": "text/html"},
                    {"URL": "https://example.org/paper.pdf", "content-type": "application/pdf"},
                ],
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


def test_parse_crossref_response_maps_fields():
    items = _parse_crossref_response(CROSSREF_JSON)
    assert len(items) == 1
    item = items[0]
    assert item.source == "crossref"
    assert item.title == "Low-Rank Adaptation for Vision Models"
    assert item.authors == ["Edward Hu", "Yelong Shen"]
    assert item.abstract == "We propose a low-rank adaptation method."
    assert item.external_id == "10.1145/ABC.123"
    assert item.year == 2024
    assert item.citation_count == 37
    assert item.pdf_url == "https://example.org/paper.pdf"


def test_parse_crossref_response_skips_items_without_title():
    items = _parse_crossref_response({"message": {"items": [{"DOI": "10.1/x"}]}})
    assert items == []


def test_parse_crossref_response_handles_empty_payload():
    assert _parse_crossref_response({}) == []
    assert _parse_crossref_response({"message": {}}) == []


async def test_search_sends_query_rows_select_and_mailto():
    client = FakeClient(CROSSREF_JSON)
    service = CrossrefService(client=client, mailto="student@example.edu")
    items = await service.search("LoRA", limit=7)
    assert items[0].title == "Low-Rank Adaptation for Vision Models"
    assert client.last_params["query"] == "LoRA"
    assert client.last_params["rows"] == 7
    assert "DOI" in client.last_params["select"]
    assert client.last_params["mailto"] == "student@example.edu"


async def test_search_sends_year_range_filter():
    client = FakeClient(CROSSREF_JSON)
    service = CrossrefService(client=client)
    await service.search("LoRA", limit=7, year_from=2024, year_to=2026)
    assert client.last_params["filter"] == (
        "from-pub-date:2024-01-01,until-pub-date:2026-12-31"
    )


async def test_search_omits_filter_and_mailto_when_unset():
    client = FakeClient(CROSSREF_JSON)
    service = CrossrefService(client=client)
    await service.search("LoRA", limit=7)
    assert "filter" not in client.last_params
    assert "mailto" not in client.last_params
