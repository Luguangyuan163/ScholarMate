"""来源注册表与检索编排器的装配。

按需组装：只有在调用多关键词检索时才读取 `app.state` 上的各来源服务，
避免应用启动阶段就与来源实现耦合（测试替身也因此不必实现全部属性）。
"""

from __future__ import annotations

from app.services.paper_source import PaperSource, SourceRegistry
from app.services.paper_store import PaperStore
from app.services.search_orchestrator import SearchOrchestrator

# (来源名, app.state 上的属性名)
SOURCE_SLOTS: tuple[tuple[str, str], ...] = (
    ("arxiv", "arxiv_service"),
    ("s2", "s2_service"),
    ("openalex", "openalex_service"),
    ("crossref", "crossref_service"),
    ("europepmc", "europepmc_service"),
    ("doaj", "doaj_service"),
)


class NamedSource:
    """为未声明 `name` 的服务补齐来源名（测试替身或后续替换实现都适用）。"""

    def __init__(self, name: str, service) -> None:
        self.name = name
        self.domains = tuple(getattr(service, "domains", ("general",)))
        self._service = service

    async def search(
        self,
        query: str,
        limit: int = 10,
        *,
        year_from: int | None = None,
        year_to: int | None = None,
    ):
        return await self._service.search(
            query, limit, year_from=year_from, year_to=year_to
        )


def build_source_registry(state) -> SourceRegistry:
    """从 `app.state` 上已注册的来源服务组装注册表。"""
    sources: list[PaperSource] = []
    for name, attribute in SOURCE_SLOTS:
        service = getattr(state, attribute, None)
        if service is None:
            continue
        sources.append(service if getattr(service, "name", "") else NamedSource(name, service))
    return SourceRegistry(sources)


def build_orchestrator(app) -> SearchOrchestrator:
    return SearchOrchestrator(
        registry=build_source_registry(app.state),
        store=PaperStore(app.state.database),
        db=app.state.database,
    )
