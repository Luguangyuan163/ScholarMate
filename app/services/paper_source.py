"""学术来源的统一契约与注册表。

对应设计文档第 4.2 节。`search` 的第二个参数是返回条数上限，按位置传入，
各来源内部可以叫 `limit` 或 `max_results`，调用方不依赖参数名。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

from app.schemas.search import PaperItem

ALL_SOURCES = "all"
DEFAULT_SOURCE_TIMEOUT_SECONDS = 12.0


class NotSupportedError(Exception):
    """来源不具备该能力，例如 arXiv 不提供引用关系。"""


@runtime_checkable
class PaperSource(Protocol):
    """论文来源契约。"""

    name: str
    domains: tuple[str, ...]

    async def search(
        self,
        query: str,
        limit: int = 10,
        *,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[PaperItem]: ...


@dataclass
class SourceResult:
    """单个来源的检索结果；失败只影响该来源自身。"""

    name: str
    items: list[PaperItem] = field(default_factory=list)
    failed: bool = False
    reason: str = ""


class SourceRegistry:
    """来源注册表：按名称选择来源，并做并行检索与失败隔离。"""

    def __init__(self, sources: Sequence[PaperSource]) -> None:
        self._sources = {source.name: source for source in sources}

    def names(self) -> list[str]:
        return list(self._sources)

    def get(self, name: str) -> PaperSource | None:
        return self._sources.get(name)

    def select(self, requested: Sequence[str] | None = None) -> list[PaperSource]:
        """`None` 或包含 `all` 时返回全部来源。"""
        if not requested or ALL_SOURCES in requested:
            return list(self._sources.values())
        return [
            self._sources[name] for name in requested if name in self._sources
        ]

    async def search(
        self,
        query: str,
        requested: Sequence[str] | None = None,
        limit: int = 10,
        *,
        year_from: int | None = None,
        year_to: int | None = None,
        timeout: float = DEFAULT_SOURCE_TIMEOUT_SECONDS,
    ) -> list[SourceResult]:
        sources = self.select(requested)
        tasks = [
            self._search_one(source, query, limit, year_from, year_to, timeout)
            for source in sources
        ]
        return list(await asyncio.gather(*tasks))

    async def _search_one(
        self,
        source: PaperSource,
        query: str,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        timeout: float,
    ) -> SourceResult:
        try:
            items = await asyncio.wait_for(
                source.search(query, limit, year_from=year_from, year_to=year_to),
                timeout=timeout,
            )
        except TimeoutError:
            return SourceResult(name=source.name, failed=True, reason="请求超时")
        except httpx.HTTPError as exc:
            return SourceResult(
                name=source.name, failed=True, reason=f"HTTP 错误: {exc}"[:120]
            )
        except NotSupportedError as exc:
            return SourceResult(name=source.name, failed=True, reason=str(exc)[:120])
        return SourceResult(name=source.name, items=list(items))
