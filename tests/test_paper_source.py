"""来源注册表行为：选择、并行检索与失败隔离。"""

from __future__ import annotations

import httpx

from app.schemas.search import PaperItem
from app.services.paper_source import ALL_SOURCES, SourceRegistry


class StubSource:
    def __init__(self, name: str, items: list[PaperItem] | None = None, error=None):
        self.name = name
        self.domains = ("general",)
        self._items = items or []
        self._error = error
        self.calls: list[tuple] = []

    async def search(self, query, limit=10, *, year_from=None, year_to=None):
        self.calls.append((query, limit, year_from, year_to))
        if self._error is not None:
            raise self._error
        return list(self._items)


def _item(title: str, source: str) -> PaperItem:
    return PaperItem(title=title, source=source, external_id=f"{source}-1")


def test_select_all_returns_every_source():
    registry = SourceRegistry([StubSource("arxiv"), StubSource("dblp")])
    assert [source.name for source in registry.select([ALL_SOURCES])] == [
        "arxiv",
        "dblp",
    ]
    assert registry.names() == ["arxiv", "dblp"]


def test_select_filters_requested_and_ignores_unknown():
    registry = SourceRegistry([StubSource("arxiv"), StubSource("dblp")])
    selected = registry.select(["dblp", "unknown"])
    assert [source.name for source in selected] == ["dblp"]


async def test_search_collects_results_and_passes_filters():
    arxiv = StubSource("arxiv", [_item("A", "arxiv")])
    dblp = StubSource("dblp", [_item("B", "dblp")])
    registry = SourceRegistry([arxiv, dblp])

    results = await registry.search("LoRA", limit=3, year_from=2024, year_to=2026)

    assert {result.name for result in results} == {"arxiv", "dblp"}
    assert sum(len(result.items) for result in results) == 2
    assert arxiv.calls == [("LoRA", 3, 2024, 2026)]


async def test_one_failing_source_does_not_break_others():
    broken = StubSource("dblp", error=httpx.ConnectError("boom"))
    healthy = StubSource("arxiv", [_item("A", "arxiv")])
    registry = SourceRegistry([broken, healthy])

    results = {result.name: result for result in await registry.search("LoRA")}

    assert results["dblp"].failed is True
    assert "boom" in results["dblp"].reason
    assert results["arxiv"].failed is False
    assert len(results["arxiv"].items) == 1


async def test_slow_source_is_reported_as_timeout():
    class SlowSource(StubSource):
        async def search(self, query, limit=10, *, year_from=None, year_to=None):
            import asyncio

            await asyncio.sleep(0.2)
            return []

    registry = SourceRegistry([SlowSource("slow"), StubSource("arxiv")])
    results = {result.name: result for result in await registry.search("x", timeout=0.01)}
    assert results["slow"].failed is True
    assert results["slow"].reason == "请求超时"
