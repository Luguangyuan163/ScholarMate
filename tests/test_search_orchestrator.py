"""多关键词检索编排：查询生成、归一去重、打分与落库。"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.core.database import Database
from app.main import create_app
from app.models.paper import Paper, SearchSession, SearchSessionPaper
from app.schemas.search import PaperItem, SearchRunRequest
from app.services.paper_source import SourceRegistry
from app.services.paper_store import PaperStore
from app.services.search_orchestrator import (
    SearchOrchestrator,
    build_queries,
    candidates_from_key,
    collect_candidates,
    normalize_keywords,
    rank_candidates,
)


class StubSource:
    def __init__(self, name: str, items: list[PaperItem], error=None) -> None:
        self.name = name
        self.domains = ("general",)
        self._items = items
        self._error = error
        self.queries: list[str] = []

    async def search(self, query, limit=10, *, year_from=None, year_to=None):
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        return list(self._items)


def _item(
    title: str,
    source: str,
    *,
    doi: str = "",
    citation_count: int = 0,
    year: int = 2024,
    abstract: str = "",
) -> PaperItem:
    return PaperItem(
        title=title,
        authors=["Test Author"],
        abstract=abstract or f"{title} 摘要",
        source=source,
        external_id=doi or f"{source}-1",
        year=year,
        citation_count=citation_count,
        url=f"https://doi.org/{doi}" if doi else "",
    )


def test_normalize_keywords_dedupes_and_strips():
    assert normalize_keywords(["  LoRA ", "lora", "", "医学影像"]) == ["LoRA", "医学影像"]


def test_build_queries_single_keyword():
    assert build_queries(["LoRA"]) == ["LoRA"]


def test_build_queries_pairs_and_combined_without_duplication():
    assert build_queries(["LoRA", "医学影像"]) == ["LoRA", "医学影像", "LoRA 医学影像"]


def test_build_queries_is_capped():
    keywords = [f"kw{i}" for i in range(8)]
    queries = build_queries(keywords)
    assert len(queries) == 8
    assert queries[:8] == keywords


def test_candidates_from_key_prefers_doi_then_fingerprint():
    with_doi = _item("A", "arxiv", doi="10.1000/xyz")
    assert candidates_from_key(with_doi) == "doi:10.1000/xyz"

    same_title_other_source = _item("A study", "doaj")
    other = _item("A study", "crossref")
    assert candidates_from_key(same_title_other_source) == candidates_from_key(other)


def test_collect_candidates_merges_sources_and_keywords():
    candidates: dict = {}
    collect_candidates(
        candidates,
        [_item("Shared Paper", "arxiv", doi="10.1000/x")],
        "LoRA",
        ["LoRA", "医学影像"],
    )
    collect_candidates(
        candidates,
        [_item("Shared Paper", "crossref", doi="10.1000/X")],
        "LoRA 医学影像",
        ["LoRA", "医学影像"],
    )

    assert len(candidates) == 1
    candidate = next(iter(candidates.values()))
    assert candidate.sources == {"arxiv", "crossref"}
    assert candidate.keywords == {"LoRA", "医学影像"}


def test_rank_candidates_prefers_keyword_hits_and_citations():
    candidates: dict = {}
    collect_candidates(
        candidates,
        [_item("Weak", "arxiv", doi="10.1000/a", citation_count=0, year=2015)],
        "LoRA",
        ["LoRA", "医学影像"],
    )
    collect_candidates(
        candidates,
        [_item("Strong", "openalex", doi="10.1000/b", citation_count=500, year=2025)],
        "LoRA 医学影像",
        ["LoRA", "医学影像"],
    )

    ranked = rank_candidates(candidates, ["LoRA", "医学影像"], current_year=2026)
    assert [candidate.primary.title for candidate, _ in ranked] == ["Strong", "Weak"]
    assert ranked[0][1] > ranked[1][1]


async def _run_orchestrator(tmp_path, sources, keywords):
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'orch.db').as_posix()}")
    await db.create_all()
    orchestrator = SearchOrchestrator(
        registry=SourceRegistry(sources),
        store=PaperStore(db),
        db=db,
    )
    response = await orchestrator.run(
        SearchRunRequest(keywords=keywords, sources=["all"], per_source=5)
    )
    return db, response


async def test_run_persists_session_papers_and_links(tmp_path):
    arxiv = StubSource(
        "arxiv",
        [
            _item("Shared Paper", "arxiv", doi="10.1000/shared", citation_count=10),
            _item("Only Arxiv", "arxiv", doi="10.1000/only-a"),
        ],
    )
    crossref = StubSource(
        "crossref",
        [_item("Shared Paper", "crossref", doi="10.1000/SHARED", citation_count=99)],
    )

    db, response = await _run_orchestrator(tmp_path, [arxiv, crossref], ["LoRA", "医学影像"])

    assert response.merged == 2
    assert response.total == 3
    assert response.by_source == {"arxiv": 2, "crossref": 1}

    async with db.session_factory() as session:
        papers = list((await session.execute(select(Paper))).scalars().all())
        sessions = list((await session.execute(select(SearchSession))).scalars().all())
        links = list(
            (await session.execute(select(SearchSessionPaper))).scalars().all()
        )

    assert len(papers) == 2
    shared = [paper for paper in papers if paper.doi == "10.1000/shared"]
    assert len(shared) == 1
    assert shared[0].citation_count == 99  # 合并时引用量取大
    assert set(json.loads(shared[0].sources_json)) == {"arxiv", "crossref"}

    assert len(sessions) == 1
    assert json.loads(sessions[0].keywords_json) == ["LoRA", "医学影像"]
    assert sessions[0].result_count == 2
    assert {link.session_id for link in links} == {sessions[0].id}
    assert len(links) == 2
    await db.close()


async def test_run_reports_failing_source_without_breaking_others(tmp_path):
    import httpx

    healthy = StubSource("arxiv", [_item("Fine", "arxiv", doi="10.1000/ok")])
    broken = StubSource("crossref", [], error=httpx.ConnectError("down"))

    db, response = await _run_orchestrator(tmp_path, [healthy, broken], ["LoRA"])

    assert response.failed_sources == ["crossref"]
    assert response.merged == 1
    await db.close()


def test_api_run_endpoint_uses_registry(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}",
        chroma_persist_dir=tmp_path / "chroma",
        pdf_upload_dir=tmp_path / "uploads",
        app_host="127.0.0.1",
        app_port=0,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        app.state.search_orchestrator = SearchOrchestrator(
            registry=SourceRegistry(
                [StubSource("arxiv", [_item("API Paper", "arxiv", doi="10.1000/api")])]
            ),
            store=PaperStore(app.state.database),
            db=app.state.database,
        )
        sources = client.get("/api/search/sources")
        assert sources.status_code == 200
        assert "arxiv" in sources.json()["sources"]

        resp = client.post("/api/search/run", json={"keywords": ["LoRA"], "per_source": 3})
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] == 1
        assert body["items"][0]["title"] == "API Paper"

        empty = client.post("/api/search/run", json={"keywords": []})
        assert empty.status_code == 422
