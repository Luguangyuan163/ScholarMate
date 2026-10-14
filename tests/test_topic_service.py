"""主题仓储行为：CRUD、合并、论文归属与关键词规则分类。"""

from __future__ import annotations

import pytest

from app.core.database import Database
from app.schemas.search import PaperItem
from app.services.paper_store import PaperStore
from app.services.topic_service import TopicStore


@pytest.fixture
async def db(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'topics.db').as_posix()}")
    await database.create_all()
    yield database
    await database.close()


async def _seed_paper(db: Database, title: str, doi: str) -> int:
    paper = await PaperStore(db).upsert(
        PaperItem(
            title=title,
            authors=["Author"],
            source="crossref",
            external_id=doi,
            year=2025,
        )
    )
    return paper.id


async def test_create_list_update_delete(db):
    store = TopicStore(db)
    topic = await store.create("大模型微调", keywords=["LoRA", "微调"])
    assert topic.id > 0

    summaries = await store.list_topics()
    assert [summary.name for summary in summaries] == ["大模型微调"]
    assert summaries[0].keywords == ["LoRA", "微调"]
    assert summaries[0].paper_count == 0

    updated = await store.update(topic.id, name="参数高效微调", color="#a8452c")
    assert updated is not None
    assert updated.name == "参数高效微调"
    assert updated.color == "#a8452c"

    assert await store.delete(topic.id) is True
    assert await store.list_topics() == []
    assert await store.delete(topic.id) is False


async def test_assign_remove_and_count_papers(db):
    store = TopicStore(db)
    topic = await store.create("医学影像")
    first = await _seed_paper(db, "CT segmentation", "10.1000/ct")
    second = await _seed_paper(db, "MRI denoising", "10.1000/mri")

    assert await store.assign_papers(topic.id, [first, second]) == 2
    assert await store.assign_papers(topic.id, [first, second]) == 0  # 幂等

    summaries = await store.list_topics()
    assert summaries[0].paper_count == 2

    papers = await store.papers_for_topic(topic.id)
    assert {paper.id for paper in papers} == {first, second}

    topics_of_paper = await store.topics_for_paper(first)
    assert [summary.name for summary in topics_of_paper] == ["医学影像"]

    assert await store.remove_papers(topic.id, [first]) == 1
    assert (await store.list_topics())[0].paper_count == 1


async def test_delete_topic_keeps_papers(db):
    store = TopicStore(db)
    topic = await store.create("临时主题")
    paper_id = await _seed_paper(db, "Keep me", "10.1000/keep")
    await store.assign_papers(topic.id, [paper_id])

    await store.delete(topic.id)

    assert await PaperStore(db).get_paper(paper_id) is not None
    assert await store.topics_for_paper(paper_id) == []


async def test_merge_moves_assignments_and_archives_source(db):
    store = TopicStore(db)
    source = await store.create("LoRA")
    target = await store.create("参数高效微调")
    first = await _seed_paper(db, "Paper A", "10.1000/a")
    second = await _seed_paper(db, "Paper B", "10.1000/b")
    await store.assign_papers(source.id, [first, second])
    await store.assign_papers(target.id, [second])

    moved = await store.merge(source.id, target.id)

    assert moved == 1  # second 已存在于目标主题，只迁移 first
    summaries = {summary.name: summary for summary in await store.list_topics()}
    assert "LoRA" not in summaries  # 已被归档
    assert summaries["参数高效微调"].paper_count == 2

    archived = {summary.name for summary in await store.list_topics(include_archived=True)}
    assert "LoRA" in archived


async def test_merge_same_topic_is_noop(db):
    store = TopicStore(db)
    topic = await store.create("自合并")
    assert await store.merge(topic.id, topic.id) == 0


async def test_classify_keywords_matches_topic_rules(db):
    store = TopicStore(db)
    await store.create("大模型微调", keywords=["LoRA", "Low-Rank Adaptation", "微调"])
    await store.create("兽医影像", keywords=["veterinary", "影像诊断"])

    matches = await store.classify_keywords(["lora", "医学影像"])

    assert [match.name for match in matches] == ["大模型微调"]
    assert matches[0].matched_keywords == ["LoRA"]
    assert matches[0].confidence == round(1 / 3, 4)


async def test_classify_ignores_archived_topics(db):
    store = TopicStore(db)
    topic = await store.create("旧主题", keywords=["LoRA"])
    await store.update(topic.id, archived=True)
    assert await store.classify_keywords(["LoRA"]) == []


async def test_auto_assign_marks_keyword_source(db):
    store = TopicStore(db)
    topic = await store.create("大模型微调", keywords=["LoRA"])
    paper_id = await _seed_paper(db, "LoRA paper", "10.1000/lora")

    matches = await store.auto_assign(["LoRA"], [paper_id])

    assert [match.topic_id for match in matches] == [topic.id]
    summaries = await store.list_topics()
    assert summaries[0].paper_count == 1
