"""OpenAlex 服务测试：JSON 解析、查询参数与详情归一化（httpx 客户端使用替身）。"""

from __future__ import annotations

from app.services.openalex_service import OpenAlexService, _parse_openalex_response

OPENALEX_JSON = {
    "results": [
        {
            "id": "https://openalex.org/W2741809807",
            "doi": "https://doi.org/10.48550/arXiv.2106.09685",
            "title": "LoRA: Low-Rank Adaptation of Large Language Models",
            "publication_year": 2021,
            "cited_by_count": 1200,
            "authorships": [{"author": {"display_name": "Edward J. Hu"}}],
            "abstract_inverted_index": {
                "We": [0],
                "propose": [1],
                "adaptation": [2],
                "low-rank": [3],
            },
        }
    ]
}


class FakeOpenAlexResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self) -> dict:
        return self._payload


class FakeOpenAlexClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.last_url = None
        self.last_params = None

    async def get(self, url, params=None, headers=None):
        self.last_url = url
        self.last_params = params
        return FakeOpenAlexResponse(self._payload)


def test_parse_openalex_response():
    items = _parse_openalex_response(OPENALEX_JSON)
    assert len(items) == 1
    item = items[0]
    assert item.source == "openalex"
    assert item.title == "LoRA: Low-Rank Adaptation of Large Language Models"
    assert item.citation_count == 1200
    assert item.external_id == "W2741809807"
    assert item.authors == ["Edward J. Hu"]
    assert item.year == 2021
    assert item.abstract == "We propose adaptation low-rank"


def test_parse_openalex_response_missing_fields():
    items = _parse_openalex_response({"results": [{"id": "https://openalex.org/W1"}]})
    assert len(items) == 1
    assert items[0].abstract == ""
    assert items[0].citation_count == 0
    assert items[0].authors == []
    assert items[0].external_id == "W1"


async def test_search_sends_query_per_page_and_mailto():
    client = FakeOpenAlexClient(OPENALEX_JSON)
    service = OpenAlexService(client=client, mailto="student@example.edu")
    items = await service.search("LoRA", limit=5)
    assert items[0].title == "LoRA: Low-Rank Adaptation of Large Language Models"
    assert client.last_params["search"] == "LoRA"
    assert client.last_params["per-page"] == 5
    assert client.last_params["mailto"] == "student@example.edu"


async def test_search_omits_mailto_when_unset():
    client = FakeOpenAlexClient(OPENALEX_JSON)
    service = OpenAlexService(client=client)
    await service.search("LoRA", limit=5)
    assert "mailto" not in client.last_params


async def test_search_sends_single_year_filter():
    client = FakeOpenAlexClient(OPENALEX_JSON)
    service = OpenAlexService(client=client)
    await service.search("LoRA", limit=5, year_from=2026, year_to=2026)
    assert client.last_params["filter"] == "publication_year:2026"


async def test_search_sends_year_range_filter():
    client = FakeOpenAlexClient(OPENALEX_JSON)
    service = OpenAlexService(client=client)
    await service.search("LoRA", limit=5, year_from=2024, year_to=2026)
    assert client.last_params["filter"] == "publication_year:2024-2026"


async def test_search_omits_year_filter_when_unset():
    client = FakeOpenAlexClient(OPENALEX_JSON)
    service = OpenAlexService(client=client)
    await service.search("LoRA", limit=5)
    assert "filter" not in client.last_params


async def test_get_paper_detail_requests_work_and_normalizes():
    detail = {
        "id": "https://openalex.org/W2741809807",
        "title": "Detail",
        "publication_year": 2021,
        "cited_by_count": 42,
        "abstract_inverted_index": {"Some": [0], "text": [1]},
    }

    class FakeDetailResponse:
        def raise_for_status(self):
            return None

        def json(self) -> dict:
            return detail

    class FakeDetailClient:
        def __init__(self) -> None:
            self.last_url = None
            self.last_params = None

        async def get(self, url, params=None, headers=None):
            self.last_url = url
            self.last_params = params
            return FakeDetailResponse()

    client = FakeDetailClient()
    service = OpenAlexService(client=client, mailto="a@b.c")
    data = await service.get_paper_detail("W2741809807")
    assert client.last_url.endswith("/works/W2741809807")
    assert client.last_params["mailto"] == "a@b.c"
    assert data["title"] == "Detail"
    assert data["citationCount"] == 42
    assert data["abstract"] == "Some text"
