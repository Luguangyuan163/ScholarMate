"""Semantic Scholar 服务测试：JSON 解析与查询参数（httpx 客户端使用替身）。"""

from __future__ import annotations

from app.services.semantic_scholar_service import SemanticScholarService, _parse_s2_response

S2_JSON = {
    "data": [
        {
            "paperId": "abc123",
            "title": "LoRA: Low-Rank Adaptation of Large Language Models",
            "abstract": "We propose Low-Rank Adaptation.",
            "authors": [{"name": "Edward J. Hu"}],
            "year": 2021,
            "citationCount": 1200,
            "externalIds": {"ArXiv": "2106.09685"},
            "url": "https://www.semanticscholar.org/paper/abc123",
            "openAccessPdf": {"url": "https://arxiv.org/pdf/2106.09685v2"},
        }
    ]
}


class FakeS2Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self) -> dict:
        return self._payload


class FakeS2Client:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.last_params = None
        self.last_headers = None

    async def get(self, url, params=None, headers=None):
        self.last_params = params
        self.last_headers = headers
        return FakeS2Response(self._payload)


def test_parse_s2_response():
    items = _parse_s2_response(S2_JSON)
    assert len(items) == 1
    item = items[0]
    assert item.source == "s2"
    assert item.citation_count == 1200
    assert item.external_id == "2106.09685"
    assert item.authors == ["Edward J. Hu"]
    assert item.year == 2021
    assert item.pdf_url == "https://arxiv.org/pdf/2106.09685v2"


def test_parse_s2_response_falls_back_to_arxiv_pdf():
    payload = {
        "data": [
            {
                "paperId": "abc124",
                "title": "No OA paper",
                "authors": [],
                "year": 2022,
                "citationCount": 3,
                "externalIds": {"ArXiv": "2201.00001"},
                "url": "https://www.semanticscholar.org/paper/abc124",
                "openAccessPdf": None,
            }
        ]
    }
    items = _parse_s2_response(payload)
    assert items[0].pdf_url == "https://arxiv.org/pdf/2201.00001"


def test_parse_s2_response_without_any_pdf():
    payload = {
        "data": [
            {
                "paperId": "abc125",
                "title": "No link",
                "authors": [],
                "year": 2022,
                "citationCount": 3,
                "externalIds": {},
                "url": "https://www.semanticscholar.org/paper/abc125",
                "openAccessPdf": None,
            }
        ]
    }
    items = _parse_s2_response(payload)
    assert items[0].pdf_url == ""


async def test_search_sends_query_fields_and_key():
    client = FakeS2Client(S2_JSON)
    service = SemanticScholarService(client=client, api_key="test-key")
    items = await service.search("LoRA", limit=5)
    assert items[0].title == "LoRA: Low-Rank Adaptation of Large Language Models"
    assert client.last_params["query"] == "LoRA"
    assert client.last_params["limit"] == 5
    assert "citationCount" in client.last_params["fields"]
    assert client.last_headers["x-api-key"] == "test-key"


async def test_search_sends_single_year_param():
    client = FakeS2Client(S2_JSON)
    service = SemanticScholarService(client=client)
    await service.search("LoRA", limit=5, year_from=2026, year_to=2026)
    assert client.last_params["year"] == "2026"


async def test_search_sends_year_range_param():
    client = FakeS2Client(S2_JSON)
    service = SemanticScholarService(client=client)
    await service.search("LoRA", limit=5, year_from=2024, year_to=2026)
    assert client.last_params["year"] == "2024-2026"


async def test_search_omits_year_param_when_unset():
    client = FakeS2Client(S2_JSON)
    service = SemanticScholarService(client=client)
    await service.search("LoRA", limit=5)
    assert "year" not in client.last_params


async def test_get_paper_detail_sends_fields():
    class FakeDetailResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"paperId": "abc", "title": "Detail", "citationCount": 5}

    class FakeDetailClient:
        def __init__(self) -> None:
            self.last_params = None
            self.last_url = None

        async def get(self, url, params=None, headers=None):
            self.last_url = url
            self.last_params = params
            return FakeDetailResponse()

    client = FakeDetailClient()
    service = SemanticScholarService(client=client, api_key="k")
    data = await service.get_paper_detail("abc")
    assert data["title"] == "Detail"
    assert data["citationCount"] == 5
    assert "citationCount" in client.last_params["fields"]
    assert client.last_url.endswith("/paper/abc")
