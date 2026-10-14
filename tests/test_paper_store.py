"""论文实体入库与跨来源合并行为。

这一组用例对应设计文档第 4.3 节（归一与去重）与第 7.3 节（多检索关联）：
同一篇论文在不同来源、不同次检索中都必须收敛到同一条记录。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.database import Database
from app.models.paper import Paper, SearchSession, SearchSessionPaper
from app.schemas.search import PaperItem
from app.services.paper_store import PaperStore


@pytest.fixture
async def db(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'papers.db').as_posix()}")
    await database.create_all()
    yield database
    await database.close()


async def _all_papers(db: Database) -> list[Paper]:
    async with db.session_factory() as session:
        return list((await session.execute(select(Paper))).scalars().all())


async def test_same_doi_from_two_sources_merges_into_one_row(db):
    store = PaperStore(db)
    await store.upsert(
        PaperItem(
            title="Low-Rank Adaptation of Large Language Models",
            authors=["Hu, E."],
            abstract="短摘要",
            source="arxiv",
            external_id="2401.12345",
            year=2021,
            citation_count=10,
            url="https://arxiv.org/abs/2401.12345",
            pdf_url="https://arxiv.org/pdf/2401.12345",
        ),
        extra_ids={"doi": "10.1000/LORA", "arxiv_id": "2401.12345"},
    )
    await store.upsert(
        PaperItem(
            title="Low-Rank Adaptation of Large Language Models",
            authors=["Hu, E.", "Shen, Y."],
            abstract="这是一个更长的摘要，包含更多细节与背景描述。",
            source="openalex",
            external_id="W123",
            year=2021,
            citation_count=42,
            url="https://doi.org/10.1000/lora",
        ),
        extra_ids={"doi": "10.1000/lora", "openalex_id": "W123"},
    )

    papers = await _all_papers(db)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.doi == "10.1000/lora"
    assert paper.citation_count == 42
    assert paper.abstract.startswith("这是一个更长的摘要")
    assert set(json.loads(paper.authors_json)) == {"Hu, E.", "Shen, Y."}
    assert set(json.loads(paper.sources_json)) == {"arxiv", "openalex"}
    assert paper.arxiv_id == "2401.12345"
    assert paper.openalex_id == "W123"


async def test_paper_without_doi_is_deduped_by_fingerprint(db):
    store = PaperStore(db)
    first = await store.upsert(
        PaperItem(
            title="Stochastic Gap: Reliability Modelling",
            authors=["Smith, J."],
            source="crossref",
            external_id="cr-1",
            year=2025,
        )
    )
    second = await store.upsert(
        PaperItem(
            title="stochastic gap reliability modelling",
            authors=["Smith, J."],
            source="europepmc",
            external_id="pmc-9",
            year=2025,
        )
    )

    assert first.id == second.id
    papers = await _all_papers(db)
    assert len(papers) == 1
    assert set(json.loads(papers[0].sources_json)) == {"crossref", "europepmc"}


async def test_same_paper_in_two_sessions_reuses_one_node(db):
    """多检索关联：两次检索命中同一篇论文时，图里必须是同一个节点。"""
    store = PaperStore(db)
    async with db.session_factory() as session:
        session_one = SearchSession(keywords_json='["LoRA"]', sources_json='["all"]')
        session_two = SearchSession(keywords_json='["低秩适配"]', sources_json='["all"]')
        session.add_all([session_one, session_two])
        await session.commit()
        session_one_id, session_two_id = session_one.id, session_two.id

    item = PaperItem(
        title="LoRA: Low-Rank Adaptation",
        authors=["Hu, E."],
        source="arxiv",
        external_id="2401.12345",
        year=2021,
    )
    first = await store.upsert(item, extra_ids={"arxiv_id": "2401.12345"})
    second = await store.upsert(
        PaperItem(
            title="LoRA: Low-Rank Adaptation",
            authors=["Hu, E."],
            source="s2",
            external_id="s2-777",
            year=2021,
        ),
        extra_ids={"arxiv_id": "2401.12345", "s2_id": "s2-777"},
    )
    assert first.id == second.id

    await store.link_session(session_one_id, first.id, rank=0, score=0.9)
    await store.link_session(session_two_id, first.id, rank=0, score=0.8)

    async with db.session_factory() as session:
        links = list(
            (await session.execute(select(SearchSessionPaper))).scalars().all()
        )
    assert {link.session_id for link in links} == {session_one_id, session_two_id}
    assert {link.paper_id for link in links} == {first.id}
