"""知识图谱：单次检索图谱、历史综合图谱与按需扩展。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.core.database import Database
from app.main import create_app
from app.models.paper import PaperEdge, SearchSession
from app.schemas.search import PaperItem
from app.services.graph_service import GraphService
from app.services.paper_store import PaperStore
from app.services.topic_service import TopicStore


@pytest.fixture
async def seeded(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'graph.db').as_posix()}")
    await db.create_all()
    store = PaperStore(db)
    topics = TopicStore(db)
    topic = await topics.create("大模型微调", keywords=["LoRA"])
    first = await store.upsert(
        PaperItem(
            title="LoRA paper",
            authors=["A"],
            source="crossref",
            external_id="10.1000/one",
            year=2024,
            citation_count=10,
        )
    )
    second = await store.upsert(
        PaperItem(
            title="Veterinary CT paper",
            authors=["B"],
            source="openalex",
            external_id="W2",
            year=2025,
            citation_count=2,
        ),
        extra_ids={"openalex_id": "W2"},
    )
    async with db.session_factory() as session:
        row = SearchSession(
            keywords_json='["LoRA"]', sources_json='["all"]', result_count=2
        )
        session.add(row)
        await session.commit()
        session_id = row.id
    await store.link_session(
        session_id, first.id, rank=0, score=0.9, matched_keywords=["LoRA"]
    )
    await store.link_session(
        session_id, second.id, rank=1, score=0.4, matched_keywords=["LoRA"]
    )
    await topics.assign_papers(topic.id, [first.id])
    async with db.session_factory() as session:
        session.add(
            PaperEdge(
                src_paper_id=first.id,
                dst_paper_id=second.id,
                edge_type="cites",
                weight=1.0,
            )
        )
        await session.commit()
    yield db, session_id, first.id, second.id, topic.id
    await db.close()


async def test_session_graph_structure(seeded):
    db, session_id, first, second, topic_id = seeded
    graph = await GraphService(db).session_graph(session_id)

    assert graph is not None
    node_ids = {node.id for node in graph.nodes}
    assert f"session:{session_id}" in node_ids
    assert f"paper:{first}" in node_ids
    assert f"paper:{second}" in node_ids
    assert "keyword:LoRA" in node_ids
    assert f"topic:{topic_id}" in node_ids

    edge_types = {edge.type for edge in graph.edges}
    assert {"in_session", "matches", "belongs_to"} <= edge_types

    paper_node = next(node for node in graph.nodes if node.id == f"paper:{first}")
    assert paper_node.type == "paper"
    assert paper_node.meta["year"] == 2024


async def test_session_graph_unknown_returns_none(seeded):
    db, *_ = seeded
    assert await GraphService(db).session_graph(9999) is None


async def test_global_graph_merges_edges_and_reports_stats(seeded):
    db, session_id, first, second, _topic_id = seeded
    graph = await GraphService(db).global_graph()

    assert graph.stats.total == 2
    assert graph.stats.shown == 2
    assert graph.stats.truncated is False
    assert any(edge.type == "cites" for edge in graph.edges)
    assert {node.type for node in graph.nodes} >= {"paper", "topic"}

    limited = await GraphService(db).global_graph(limit=1)
    assert limited.stats.shown == 1
    assert limited.stats.truncated is True


async def test_global_graph_filters(seeded):
    db, _session_id, first, _second, topic_id = seeded
    service = GraphService(db)

    by_topic = await service.global_graph(topic_id=topic_id)
    assert by_topic.stats.total == 1

    by_year = await service.global_graph(year_from=2025)
    assert by_year.stats.total == 1

    by_citations = await service.global_graph(min_citations=5)
    assert by_citations.stats.total == 1
    assert f"paper:{first}" in {node.id for node in by_citations.nodes}

    by_source = await service.global_graph(source="openalex")
    assert by_source.stats.total == 1


class FakeOpenAlex:
    def __init__(self) -> None:
        self.work_id = "W2"
        self.calls: list[str] = []

    async def find_work_id(self, doi: str) -> str:
        self.calls.append("find")
        return self.work_id

    async def get_referenced_works(self, work_id: str, limit: int):
        self.calls.append("references")
        return [
            PaperItem(
                title="Referenced work",
                authors=["C"],
                source="openalex",
                external_id="W9",
                year=2023,
            )
        ]

    async def get_citing_works(self, work_id: str, limit: int):
        self.calls.append("citations")
        return [
            PaperItem(
                title="Citing work",
                authors=["D"],
                source="openalex",
                external_id="W10",
                year=2026,
            )
        ]


async def test_expand_adds_papers_and_edges_once(seeded):
    db, _session_id, first, _second, _topic_id = seeded
    openalex = FakeOpenAlex()
    service = GraphService(db, openalex=openalex)

    result = await service.expand(first, ["references", "citations"])

    assert result["related_papers"] == 2
    assert result["added_edges"] == 2
    async with db.session_factory() as session:
        edges = list((await session.execute(select(PaperEdge))).scalars().all())
    assert len([edge for edge in edges if edge.edge_type == "cites"]) == 3

    again = await service.expand(first, ["references"])
    assert again["added_edges"] == 0  # 幂等：重复扩展不重复建边


async def test_expand_without_openalex_reports_reason(seeded):
    db, _session_id, first, _second, _topic_id = seeded
    result = await GraphService(db, openalex=None).expand(first)
    assert result["related_papers"] == 0
    assert "未配置" in result["reason"]


def test_graph_api_endpoints(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'graph_api.db').as_posix()}",
        chroma_persist_dir=tmp_path / "chroma",
        pdf_upload_dir=tmp_path / "uploads",
        app_host="127.0.0.1",
        app_port=0,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/graph/session/999").status_code == 404
        empty = client.get("/api/graph/global")
        assert empty.status_code == 200
        assert empty.json()["stats"]["total"] == 0
        missing = client.post("/api/graph/expand", json={"paper_id": 999})
        assert missing.status_code == 404
