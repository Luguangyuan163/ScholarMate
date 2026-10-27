"""知识图谱服务：单次检索图谱、历史综合图谱与按需扩展。

对应设计文档第 7 节。两类图谱的差别在范围与合并粒度：
- 单次检索图谱：以检索会话为中心，节点是该次命中的论文、关键词与主题；
- 历史综合图谱：跨会话按论文实体合并，节点是论文与主题，边包含引用。
"""

from __future__ import annotations

import json
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.models.paper import (
    Paper,
    PaperEdge,
    PaperTopic,
    SearchSession,
    SearchSessionPaper,
    Topic,
)
from app.schemas.graph import GraphEdge, GraphNode, GraphOut, GraphStats
from app.services.paper_store import PaperStore

MAX_GLOBAL_NODES = 300
EXPAND_LIMIT = 20
PAPER_LABEL_LENGTH = 80


class GraphService:
    """图谱查询与扩展。"""

    def __init__(
        self,
        db: Database,
        paper_store: PaperStore | None = None,
        openalex=None,
    ) -> None:
        self._db = db
        self._store = paper_store or PaperStore(db)
        self._openalex = openalex

    async def session_graph(self, session_id: int) -> GraphOut | None:
        """单次检索图谱。"""
        async with self._db.session_factory() as session:
            row = await session.get(SearchSession, session_id)
            if row is None:
                return None
            links = list(
                (
                    await session.execute(
                        select(SearchSessionPaper).where(
                            SearchSessionPaper.session_id == session_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            paper_ids = [link.paper_id for link in links]
            papers = await _papers_by_id(session, paper_ids)
            assignments = await _assignments_for(session, paper_ids)
            topics = await _topics_by_id(
                session, {row.topic_id for row in assignments}
            )
        return _build_session_graph(row, links, papers, assignments, topics)

    async def global_graph(
        self,
        *,
        topic_id: int | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        source: str | None = None,
        min_citations: int = 0,
        limit: int = MAX_GLOBAL_NODES,
    ) -> GraphOut:
        """历史综合图谱：跨会话合并，按度数排序截断。"""
        conditions = _global_conditions(year_from, year_to, source, min_citations)
        base = select(Paper)
        if topic_id is not None:
            base = base.join(PaperTopic, PaperTopic.paper_id == Paper.id).where(
                PaperTopic.topic_id == topic_id
            )
        max_rows = max(1, min(limit, MAX_GLOBAL_NODES))
        async with self._db.session_factory() as session:
            total = int(
                (
                    await session.execute(
                        select(func.count()).select_from(
                            base.where(*conditions).subquery()
                        )
                    )
                ).scalar_one()
            )
            rows = list(
                (
                    await session.execute(
                        base.where(*conditions)
                        .order_by(Paper.citation_count.desc(), Paper.id.desc())
                        .limit(max_rows)
                    )
                )
                .scalars()
                .all()
            )
            paper_ids = [paper.id for paper in rows]
            assignments = await _assignments_for(session, paper_ids)
            topics = await _topics_by_id(
                session, {row.topic_id for row in assignments}
            )
            paper_edges = await _edges_between(session, paper_ids)
        graph = _build_global_graph(rows, assignments, topics, paper_edges)
        graph.stats = GraphStats(
            total=total, shown=len(rows), truncated=total > len(rows)
        )
        return graph

    async def expand(
        self,
        paper_id: int,
        kinds: list[str] | None = None,
    ) -> dict | None:
        """按需扩展引用边：拉取参考文献与被引论文，补进论文实体表与边表。"""
        paper = await self._store.get_paper(paper_id)
        if paper is None:
            return None
        if self._openalex is None:
            return {"paper_id": paper_id, "related_papers": 0, "added_edges": 0,
                    "reason": "未配置引用数据来源"}
        work_id = paper.openalex_id or await self._openalex.find_work_id(paper.doi or "")
        if not work_id:
            return {"paper_id": paper_id, "related_papers": 0, "added_edges": 0,
                    "reason": "该论文缺少 OpenAlex 标识，无法扩展引用"}
        kinds = kinds or ["references"]
        related_papers = 0
        added_edges = 0
        if "references" in kinds:
            items = await self._openalex.get_referenced_works(work_id, EXPAND_LIMIT)
            for item in items:
                related = await self._store.upsert(item)
                added_edges += await self._add_edge(paper_id, related.id, "cites")
                related_papers += 1
        if "citations" in kinds:
            items = await self._openalex.get_citing_works(work_id, EXPAND_LIMIT)
            for item in items:
                related = await self._store.upsert(item)
                added_edges += await self._add_edge(related.id, paper_id, "cites")
                related_papers += 1
        return {
            "paper_id": paper_id,
            "work_id": work_id,
            "related_papers": related_papers,
            "added_edges": added_edges,
        }

    async def _add_edge(self, src_id: int, dst_id: int, edge_type: str) -> int:
        """插入一条论文间边；已存在或自环时返回 0。"""
        if src_id == dst_id:
            return 0
        async with self._db.session_factory() as session:
            existing = await session.scalar(
                select(PaperEdge).where(
                    PaperEdge.src_paper_id == src_id,
                    PaperEdge.dst_paper_id == dst_id,
                    PaperEdge.edge_type == edge_type,
                )
            )
            if existing is not None:
                return 0
            session.add(
                PaperEdge(
                    src_paper_id=src_id,
                    dst_paper_id=dst_id,
                    edge_type=edge_type,
                )
            )
            await session.commit()
            return 1


def _build_session_graph(
    row: SearchSession,
    links: list[SearchSessionPaper],
    papers: dict[int, Paper],
    assignments: list[PaperTopic],
    topics: dict[int, Topic],
) -> GraphOut:
    keywords = _json_list(row.keywords_json)
    nodes = [
        GraphNode(
            id=f"session:{row.id}",
            type="session",
            label=" / ".join(keywords) or f"检索 {row.id}",
            size=14 + min(len(links) * 2, 20),
            group="检索",
        )
    ]
    edges: list[GraphEdge] = []
    keyword_counts: Counter[str] = Counter()
    for link in links:
        keyword_counts.update(_json_list(link.matched_keywords_json))
    for keyword, count in keyword_counts.items():
        nodes.append(
            GraphNode(
                id=f"keyword:{keyword}",
                type="keyword",
                label=keyword,
                size=10 + count * 2,
                group="关键词",
            )
        )
    topic_counts = Counter(assignment.topic_id for assignment in assignments)
    for topic_id, count in topic_counts.items():
        topic = topics.get(topic_id)
        if topic is None:
            continue
        nodes.append(
            GraphNode(
                id=f"topic:{topic_id}",
                type="topic",
                label=topic.name,
                size=14 + count * 4,
                group="主题",
                meta={"color": topic.color},
            )
        )
    for link in links:
        paper = papers.get(link.paper_id)
        if paper is None:
            continue
        nodes.append(_paper_node(paper, 12 + (link.score or 0) * 18))
        edges.append(
            GraphEdge(
                source=f"session:{row.id}",
                target=f"paper:{paper.id}",
                type="in_session",
                weight=round(link.score or 0.0, 4),
            )
        )
        for keyword in _json_list(link.matched_keywords_json):
            edges.append(
                GraphEdge(
                    source=f"paper:{paper.id}",
                    target=f"keyword:{keyword}",
                    type="matches",
                )
            )
    for assignment in assignments:
        edges.append(
            GraphEdge(
                source=f"paper:{assignment.paper_id}",
                target=f"topic:{assignment.topic_id}",
                type="belongs_to",
                weight=round(assignment.confidence or 0.0, 4),
            )
        )
    return GraphOut(
        nodes=nodes,
        edges=edges,
        stats=GraphStats(total=len(links), shown=len(links), truncated=False),
    )


def _build_global_graph(
    papers: list[Paper],
    assignments: list[PaperTopic],
    topics: dict[int, Topic],
    paper_edges: list[PaperEdge],
) -> GraphOut:
    nodes = [_paper_node(paper, 12 + min((paper.citation_count or 0) / 25, 20))
             for paper in papers]
    topic_counts = Counter(assignment.topic_id for assignment in assignments)
    for topic_id, count in topic_counts.items():
        topic = topics.get(topic_id)
        if topic is None:
            continue
        nodes.append(
            GraphNode(
                id=f"topic:{topic_id}",
                type="topic",
                label=topic.name,
                size=14 + count * 4,
                group="主题",
                meta={"color": topic.color},
            )
        )
    edges = [
        GraphEdge(
            source=f"paper:{assignment.paper_id}",
            target=f"topic:{assignment.topic_id}",
            type="belongs_to",
            weight=round(assignment.confidence or 0.0, 4),
        )
        for assignment in assignments
    ]
    edges.extend(
        GraphEdge(
            source=f"paper:{edge.src_paper_id}",
            target=f"paper:{edge.dst_paper_id}",
            type=edge.edge_type,
            weight=round(edge.weight or 0.0, 4),
        )
        for edge in paper_edges
    )
    return GraphOut(nodes=nodes, edges=edges, stats=GraphStats())


def _paper_node(paper: Paper, size: float) -> GraphNode:
    return GraphNode(
        id=f"paper:{paper.id}",
        type="paper",
        label=(paper.title or "")[:PAPER_LABEL_LENGTH],
        size=round(min(size, 40.0), 1),
        group="论文",
        meta={
            "year": paper.year,
            "citations": paper.citation_count,
            "sources": _json_list(paper.sources_json),
            "doi": paper.doi,
            "url": paper.url,
            "pdf_url": paper.pdf_url,
        },
    )


async def _papers_by_id(session: AsyncSession, ids: list[int]) -> dict[int, Paper]:
    if not ids:
        return {}
    rows = (
        (await session.execute(select(Paper).where(Paper.id.in_(ids))))
        .scalars()
        .all()
    )
    return {paper.id: paper for paper in rows}


async def _topics_by_id(session: AsyncSession, ids: set[int]) -> dict[int, Topic]:
    if not ids:
        return {}
    rows = (
        (await session.execute(select(Topic).where(Topic.id.in_(ids))))
        .scalars()
        .all()
    )
    return {topic.id: topic for topic in rows}


async def _assignments_for(
    session: AsyncSession, paper_ids: list[int]
) -> list[PaperTopic]:
    if not paper_ids:
        return []
    return list(
        (
            await session.execute(
                select(PaperTopic).where(PaperTopic.paper_id.in_(paper_ids))
            )
        )
        .scalars()
        .all()
    )


async def _edges_between(
    session: AsyncSession, paper_ids: list[int]
) -> list[PaperEdge]:
    if len(paper_ids) < 2:
        return []
    return list(
        (
            await session.execute(
                select(PaperEdge).where(
                    PaperEdge.src_paper_id.in_(paper_ids),
                    PaperEdge.dst_paper_id.in_(paper_ids),
                )
            )
        )
        .scalars()
        .all()
    )


def _global_conditions(year_from, year_to, source, min_citations) -> list:
    conditions = []
    if year_from is not None:
        conditions.append(Paper.year >= year_from)
    if year_to is not None:
        conditions.append(Paper.year <= year_to)
    if source:
        conditions.append(Paper.sources_json.like(f'%"{source}"%'))
    if min_citations:
        conditions.append(Paper.citation_count >= min_citations)
    return conditions


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
