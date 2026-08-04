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


async def test_search_sends_query_fields_and_key():
    client = FakeS2Client(S2_JSON)
    service = SemanticScholarService(client=client, api_key="test-key")
    items = await service.search("LoRA", limit=5)
    assert items[0].title == "LoRA: Low-Rank Adaptation of Large Language Models"
    assert client.last_params["query"] == "LoRA"
    assert client.last_params["limit"] == 5
    assert "citationCount" in client.last_params["fields"]
    assert client.last_headers["x-api-key"] == "test-key"
