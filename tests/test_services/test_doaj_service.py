"""DOAJ 适配器测试：字段映射、摘要标签清理与年份查询语法。

样例结构与 2026-10-14 真实响应一致（见 `_parse_doaj_response`）。
"""

from __future__ import annotations

from app.services.doaj_service import DoajService, _parse_doaj_response, build_query

DOAJ_JSON = {
    "total": 680,
    "page": 1,
    "results": [
        {
            "id": "abc123",
            "bibjson": {
                "identifier": [
                    {"id": "10.1038/s41598-025-29121-z", "type": "doi"},
                    {"id": "2045-2322", "type": "eissn"},
                ],
                "journal": {"title": "Scientific Reports", "publisher": "Nature Portfolio"},
                "year": "2025",
                "title": "Low-rank adaptation for medical image segmentation",
                "author": [{"name": "Wenjing Hong"}, {"name": "Zhengdi She"}],
                "link": [
                    {"content_type": "HTML", "type": "fulltext", "url": "https://doi.org/10.1/x"},
                    {"content_type": "PDF", "type": "fulltext", "url": "https://doaj.org/x.pdf"},
                ],
                "abstract": "Abstract Breast cancer segmentation remains challenging.",
            },
        }
    ],
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
    assert build_query("LoRA", None, None) == "LoRA"


def test_build_query_with_year_range():
    assert build_query("LoRA", 2024, 2026) == "(LoRA) AND bibjson.year:[2024 TO 2026]"


def test_parse_doaj_response_maps_fields():
    items = _parse_doaj_response(DOAJ_JSON)
    assert len(items) == 1
    item = items[0]
    assert item.source == "doaj"
    assert item.title == "Low-rank adaptation for medical image segmentation"
    assert item.authors == ["Wenjing Hong", "Zhengdi She"]
    assert item.abstract == "Breast cancer segmentation remains challenging."
    assert item.external_id == "10.1038/s41598-025-29121-z"
    assert item.year == 2025
    assert item.url == "https://doi.org/10.1038/s41598-025-29121-z"
    assert item.pdf_url == "https://doaj.org/x.pdf"
    assert item.citation_count == 0


def test_parse_doaj_without_doi_falls_back_to_fulltext_link():
    payload = {
        "results": [
            {
                "id": "xyz",
                "bibjson": {
                    "title": "No DOI article",
                    "link": [{"type": "fulltext", "url": "https://example.org/a"}],
                },
            }
        ]
    }
    items = _parse_doaj_response(payload)
    assert items[0].external_id == "xyz"
    assert items[0].url == "https://example.org/a"
    assert items[0].pdf_url == ""
    assert items[0].year is None


async def test_search_builds_encoded_url_and_page_size():
    client = FakeClient(DOAJ_JSON)
    service = DoajService(client=client)
    items = await service.search("low-rank adaptation", limit=5, year_from=2024, year_to=2026)
    assert items[0].title.startswith("Low-rank adaptation")
    assert client.last_params["pageSize"] == 5
    assert "bibjson.year%3A%5B2024%20TO%202026%5D" in client.last_url
