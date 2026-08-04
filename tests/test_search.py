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
        resp = client.post("/api/search", json={"query": "x", "source": "local"})
    assert resp.status_code == 501


def test_search_arxiv_unreachable_returns_502(app_settings):
    class UnreachableService:
        async def search(self, query, max_results=10, year_from=None, year_to=None):
            raise httpx.ReadTimeout("arxiv timeout")

    app = create_app(app_settings)
    app.state.arxiv_service = UnreachableService()
    with TestClient(app) as client:
        resp = client.post("/api/search", json={"query": "LoRA"})
    assert resp.status_code == 502
    assert "不可达" in resp.json()["detail"]


def test_search_requires_query(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post("/api/search", json={"query": ""})
    assert resp.status_code == 422
