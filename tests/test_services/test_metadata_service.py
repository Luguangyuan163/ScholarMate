"""元数据源回退测试：优先 S2，失败或无 key 时回退 OpenAlex。"""

from __future__ import annotations

import httpx
import pytest

from app.schemas.search import PaperItem
from app.services.metadata_service import FallbackMetadataSource


class FakeS2:
    def __init__(self, items=None, error=None) -> None:
        self.items = items or []
        self.error = error
        self.search_calls = 0
        self.detail_calls = 0

    async def search(self, query, limit=10, year_from=None, year_to=None):
        self.search_calls += 1
        self.last_year_from = year_from
        self.last_year_to = year_to
        if self.error:
            raise self.error
        return self.items

    async def get_paper_detail(self, paper_id):
        self.detail_calls += 1
        if self.error:
            raise self.error
        return {"title": "s2 detail", "citationCount": 1}


class FakeOpenAlex:
    def __init__(self, items=None, error=None) -> None:
        self.items = items or []
        self.error = error
        self.search_calls = 0
        self.detail_calls = 0

    async def search(self, query, limit=10, year_from=None, year_to=None):
        self.search_calls += 1
        if self.error:
            raise self.error
        return self.items

    async def get_paper_detail(self, paper_id):
        self.detail_calls += 1
        if self.error:
            raise self.error
        return {"title": "openalex detail", "citationCount": 2}


def _item(source: str) -> PaperItem:
    return PaperItem(title="t", source=source, external_id="1")


async def test_prefers_s2_when_configured():
    s2 = FakeS2(items=[_item("s2")])
    openalex = FakeOpenAlex(items=[_item("openalex")])
    source = FallbackMetadataSource(s2=s2, openalex=openalex, prefer_s2=True)
    items = await source.search("LoRA")
    assert items[0].source == "s2"
    assert s2.search_calls == 1
    assert openalex.search_calls == 0


async def test_falls_back_to_openalex_when_s2_fails():
    error = httpx.HTTPStatusError(
        "429",
        request=httpx.Request("GET", "https://api.semanticscholar.org"),
        response=httpx.Response(429),
    )
    s2 = FakeS2(error=error)
    openalex = FakeOpenAlex(items=[_item("openalex")])
    source = FallbackMetadataSource(s2=s2, openalex=openalex, prefer_s2=True)
    items = await source.search("LoRA")
    assert items[0].source == "openalex"
    assert openalex.search_calls == 1


async def test_uses_openalex_directly_without_key():
    s2 = FakeS2()
    openalex = FakeOpenAlex(items=[_item("openalex")])
    source = FallbackMetadataSource(s2=s2, openalex=openalex, prefer_s2=False)
    items = await source.search("LoRA")
    assert items[0].source == "openalex"
    assert s2.search_calls == 0


async def test_forwards_year_range_to_selected_source():
    s2 = FakeS2(items=[_item("s2")])
    source = FallbackMetadataSource(
        s2=s2, openalex=FakeOpenAlex(items=[_item("openalex")]), prefer_s2=True
    )
    await source.search("LoRA", limit=5, year_from=2025, year_to=2026)
    assert s2.last_year_from == 2025
    assert s2.last_year_to == 2026


async def test_detail_falls_back_to_openalex():
    s2 = FakeS2(error=httpx.ConnectError("down"))
    openalex = FakeOpenAlex()
    source = FallbackMetadataSource(s2=s2, openalex=openalex, prefer_s2=True)
    data = await source.get_paper_detail("W1")
    assert data["title"] == "openalex detail"
    assert openalex.detail_calls == 1


async def test_raises_when_both_sources_fail():
    error = httpx.ConnectError("both down")
    source = FallbackMetadataSource(
        s2=FakeS2(error=error),
        openalex=FakeOpenAlex(error=error),
        prefer_s2=True,
    )
    with pytest.raises(httpx.HTTPError):
        await source.search("LoRA")
