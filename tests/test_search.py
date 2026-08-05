"""搜索接口测试：arXiv 数据源（注入假服务）与参数校验。"""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.search import PaperItem


class FakeArxivService:
    def __init__(self, items: list[PaperItem]) -> None:
        self.items = items

    async def search(self, query, max_results=10, year_from=None, year_to=None):
        return self.items


def test_search_arxiv_returns_items(app_settings):
    app = create_app(app_settings)
    app.state.arxiv_service = FakeArxivService(
        [PaperItem(title="t", authors=["a"], abstract="x", source="arxiv", external_id="1")]
    )
    with TestClient(app) as client:
        resp = client.post("/api/search", json={"query": "LoRA", "max_results": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["source"] == "arxiv"


def test_search_returns_html_for_htmx(app_settings):
    app = create_app(app_settings)
    app.state.arxiv_service = FakeArxivService(
        [
            PaperItem(
                title="LoRA Paper",
                authors=["a"],
                abstract="x",
                source="arxiv",
                external_id="1",
            )
        ]
    )
    with TestClient(app) as client:
        resp = client.post(
            "/api/search",
            json={"query": "LoRA"},
            headers={"HX-Request": "true"},
        )
    assert resp.status_code == 200
    assert "LoRA Paper" in resp.text


def test_search_unsupported_source_returns_501(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post("/api/search", json={"query": "x", "source": "pubmed"})
    assert resp.status_code == 501


def test_search_arxiv_unreachable_returns_502(app_settings):
    class UnreachableService:
        async def search(self, query, max_results=10, year_from=None, year_to=None):
            raise httpx.ReadTimeout("arxiv timeout")

    class UnreachableS2:
        async def search(self, query, limit=10, year_from=None, year_to=None):
            raise httpx.ConnectError("s2 down")

    class UnreachableOpenAlex:
        async def search(self, query, limit=10, year_from=None, year_to=None):
            raise httpx.ConnectError("openalex down")

    app = create_app(app_settings)
    app.state.arxiv_service = UnreachableService()
    app.state.s2_service = UnreachableS2()
    app.state.openalex_service = UnreachableOpenAlex()
    with TestClient(app) as client:
        resp = client.post("/api/search", json={"query": "LoRA"})
    assert resp.status_code == 502
    assert "不可达" in resp.json()["detail"]


def test_search_falls_back_to_s2(app_settings):
    class BrokenArxiv:
        async def search(self, query, max_results=10, year_from=None, year_to=None):
            raise httpx.ReadTimeout("arxiv down")

    class FakeS2:
        async def search(self, query, limit=10, year_from=None, year_to=None):
            return [PaperItem(title="S2 Result", source="s2", external_id="9")]

    app = create_app(app_settings)
    app.state.arxiv_service = BrokenArxiv()
    app.state.s2_service = FakeS2()
    with TestClient(app) as client:
        resp = client.post("/api/search", json={"query": "LoRA"})
    assert resp.status_code == 200
    assert resp.json()["items"][0]["source"] == "s2"


def test_search_s2_falls_back_to_openalex(app_settings):
    class BrokenS2:
        async def search(self, query, limit=10, year_from=None, year_to=None):
            raise httpx.HTTPStatusError(
                "429",
                request=httpx.Request("GET", "https://api.semanticscholar.org"),
                response=httpx.Response(429),
            )

    class FakeOpenAlex:
        async def search(self, query, limit=10, year_from=None, year_to=None):
            return [PaperItem(title="OpenAlex Result", source="openalex", external_id="W1")]

    app = create_app(app_settings)
    app.state.s2_service = BrokenS2()
    app.state.openalex_service = FakeOpenAlex()
    with TestClient(app) as client:
        resp = client.post("/api/search", json={"query": "LoRA", "source": "s2"})
    assert resp.status_code == 200
    assert resp.json()["items"][0]["source"] == "openalex"


def test_search_uses_cache(app_settings):
    class CountingArxiv:
        def __init__(self) -> None:
            self.calls = 0

        async def search(self, query, max_results=10, year_from=None, year_to=None):
            self.calls += 1
            return [PaperItem(title="Cached", source="arxiv", external_id="1")]

    app = create_app(app_settings)
    app.state.arxiv_service = CountingArxiv()
    with TestClient(app) as client:
        first = client.post("/api/search", json={"query": "LoRA", "max_results": 3})
        second = client.post("/api/search", json={"query": "LoRA", "max_results": 3})
    assert first.json()["total"] == 1
    assert second.json()["total"] == 1
    assert app.state.arxiv_service.calls == 1


def test_search_requires_query(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post("/api/search", json={"query": ""})
    assert resp.status_code == 422
