"""主题管理与分类：CRUD、合并、论文归属，以及关键词规则分类。

对应设计文档第 6 节。归类有三个来源：用户指定（user）、关键词规则
（keyword）、模型建议（llm，后续接入）。本模块实现前两个中不依赖模型的
部分：主题维护与关键词命中判定。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.models.paper import Paper, PaperTopic, Topic

DEFAULT_COLOR = "#1f3a5f"


@dataclass
class TopicSummary:
    """主题列表项：主题本身 + 关联论文数。"""

    id: int
    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    color: str = DEFAULT_COLOR
    archived: bool = False
    paper_count: int = 0


@dataclass
class TopicMatch:
    """关键词规则命中的主题。"""

    topic_id: int
    name: str
    matched_keywords: list[str] = field(default_factory=list)
    confidence: float = 0.0


class TopicStore:
    """主题持久化与关键词分类。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_topics(self, include_archived: bool = False) -> list[TopicSummary]:
        async with self._db.session_factory() as session:
            statement = select(Topic).order_by(Topic.name)
            if not include_archived:
                statement = statement.where(Topic.archived == 0)
            topics = list((await session.execute(statement)).scalars().all())
            counts = await _paper_counts(session)
        return [_to_summary(topic, counts.get(topic.id, 0)) for topic in topics]

    async def get(self, topic_id: int) -> Topic | None:
        async with self._db.session_factory() as session:
            return await session.get(Topic, topic_id)

    async def create(
        self,
        name: str,
        description: str = "",
        keywords: list[str] | None = None,
        color: str = DEFAULT_COLOR,
    ) -> Topic:
        async with self._db.session_factory() as session:
            topic = Topic(
                name=name.strip(),
                description=description,
                keywords_json=json.dumps(keywords or [], ensure_ascii=False),
                color=color or DEFAULT_COLOR,
            )
            session.add(topic)
            await session.commit()
            return topic

    async def update(self, topic_id: int, **changes) -> Topic | None:
        """支持的字段：name / description / keywords / color / archived。"""
        async with self._db.session_factory() as session:
            topic = await session.get(Topic, topic_id)
            if topic is None:
                return None
            if changes.get("name"):
                topic.name = str(changes["name"]).strip()
            if "description" in changes and changes["description"] is not None:
                topic.description = changes["description"]
            if changes.get("keywords") is not None:
                topic.keywords_json = json.dumps(
                    changes["keywords"], ensure_ascii=False
                )
            if changes.get("color"):
                topic.color = changes["color"]
            if changes.get("archived") is not None:
                topic.archived = 1 if changes["archived"] else 0
            await session.commit()
            return topic

    async def delete(self, topic_id: int) -> bool:
        """删除主题及其归属记录；论文本身保留。"""
        async with self._db.session_factory() as session:
            topic = await session.get(Topic, topic_id)
            if topic is None:
                return False
            await session.execute(
                delete(PaperTopic).where(PaperTopic.topic_id == topic_id)
            )
            await session.delete(topic)
            await session.commit()
            return True

    async def merge(self, source_id: int, target_id: int) -> int:
        """把来源主题的论文归属并入目标主题，来源主题归档。"""
        if source_id == target_id:
            return 0
        async with self._db.session_factory() as session:
            source = await session.get(Topic, source_id)
            target = await session.get(Topic, target_id)
            if source is None or target is None:
                return 0
            existing = set(
                (
                    await session.execute(
                        select(PaperTopic.paper_id).where(
                            PaperTopic.topic_id == target_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            rows = list(
                (
                    await session.execute(
                        select(PaperTopic).where(PaperTopic.topic_id == source_id)
                    )
                )
                .scalars()
                .all()
            )
            moved = 0
            for row in rows:
                if row.paper_id not in existing:
                    session.add(
                        PaperTopic(
                            paper_id=row.paper_id,
                            topic_id=target_id,
                            confidence=row.confidence,
                            assigned_by=row.assigned_by,
                        )
                    )
                    moved += 1
                await session.delete(row)
            source.archived = 1
            await session.commit()
            return moved

    async def assign_papers(
        self,
        topic_id: int,
        paper_ids: list[int],
        *,
        assigned_by: str = "user",
        confidence: float = 1.0,
    ) -> int:
        """把论文归入主题，返回新增归属数。"""
        if not paper_ids:
            return 0
        async with self._db.session_factory() as session:
            topic = await session.get(Topic, topic_id)
            if topic is None:
                return 0
            existing = set(
                (
                    await session.execute(
                        select(PaperTopic.paper_id).where(
                            PaperTopic.topic_id == topic_id,
                            PaperTopic.paper_id.in_(paper_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            added = 0
            for paper_id in paper_ids:
                if paper_id in existing:
                    continue
                session.add(
                    PaperTopic(
                        paper_id=paper_id,
                        topic_id=topic_id,
                        confidence=confidence,
                        assigned_by=assigned_by,
                    )
                )
                added += 1
            await session.commit()
            return added

    async def remove_papers(self, topic_id: int, paper_ids: list[int]) -> int:
        if not paper_ids:
            return 0
        async with self._db.session_factory() as session:
            result = await session.execute(
                delete(PaperTopic).where(
                    PaperTopic.topic_id == topic_id,
                    PaperTopic.paper_id.in_(paper_ids),
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def topics_for_paper(self, paper_id: int) -> list[TopicSummary]:
        async with self._db.session_factory() as session:
            topics = list(
                (
                    await session.execute(
                        select(Topic)
                        .join(PaperTopic, PaperTopic.topic_id == Topic.id)
                        .where(PaperTopic.paper_id == paper_id)
                    )
                )
                .scalars()
                .all()
            )
        return [_to_summary(topic, 0) for topic in topics]

    async def papers_for_topic(
        self,
        topic_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Paper]:
        async with self._db.session_factory() as session:
            statement = (
                select(Paper)
                .join(PaperTopic, PaperTopic.paper_id == Paper.id)
                .where(PaperTopic.topic_id == topic_id)
                .order_by(Paper.citation_count.desc(), Paper.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return list((await session.execute(statement)).scalars().all())

    async def classify_keywords(self, keywords: list[str]) -> list[TopicMatch]:
        """关键词规则分类：主题关键词与检索关键词做不区分大小写的包含匹配。"""
        normalized = [keyword.strip().lower() for keyword in keywords if keyword.strip()]
        matches: list[TopicMatch] = []
        if not normalized:
            return matches
        async with self._db.session_factory() as session:
            topics = list(
                (
                    await session.execute(select(Topic).where(Topic.archived == 0))
                )
                .scalars()
                .all()
            )
        for topic in topics:
            topic_keywords = _json_list(topic.keywords_json)
            hit = [
                keyword
                for keyword in topic_keywords
                if any(keyword.lower() in query for query in normalized)
            ]
            if not hit:
                continue
            confidence = round(len(hit) / max(len(topic_keywords), 1), 4)
            matches.append(
                TopicMatch(
                    topic_id=topic.id,
                    name=topic.name,
                    matched_keywords=hit,
                    confidence=confidence,
                )
            )
        return matches

    async def auto_assign(
        self,
        keywords: list[str],
        paper_ids: list[int],
    ) -> list[TopicMatch]:
        """按关键词规则批量归类，返回命中的主题。"""
        matches = await self.classify_keywords(keywords)
        for match in matches:
            await self.assign_papers(
                match.topic_id,
                paper_ids,
                assigned_by="keyword",
                confidence=match.confidence,
            )
        return matches


async def _paper_counts(session: AsyncSession) -> dict[int, int]:
    rows = await session.execute(
        select(PaperTopic.topic_id, func.count(PaperTopic.paper_id)).group_by(
            PaperTopic.topic_id
        )
    )
    return {int(topic_id): int(count) for topic_id, count in rows.all()}


def _to_summary(topic: Topic, paper_count: int) -> TopicSummary:
    return TopicSummary(
        id=topic.id,
        name=topic.name,
        description=topic.description or "",
        keywords=_json_list(topic.keywords_json),
        color=topic.color or DEFAULT_COLOR,
        archived=bool(topic.archived),
        paper_count=paper_count,
    )


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
