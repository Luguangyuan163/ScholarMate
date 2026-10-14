"""论文实体入库：按标识查找、跨来源合并、检索会话关联。

对应设计文档第 4.3 节（归一与去重）与 7.3 节（多检索关联）。同一个
DOI 在不同来源、不同次检索中命中时，都收敛到 `papers` 表的同一行。
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.models.paper import Paper, PaperTopic, SearchSessionPaper
from app.schemas.search import PaperItem
from app.services.paper_identity import (
    normalize_arxiv_id,
    normalize_doi,
    normalize_title,
    title_fingerprint,
)

IDENTITY_COLUMNS = ("doi", "arxiv_id", "s2_id", "openalex_id")


class PaperStore:
    """论文实体的持久化入口。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self,
        item: PaperItem,
        extra_ids: dict[str, str] | None = None,
    ) -> Paper:
        """写入或合并一条论文记录，返回归一后的实体。"""
        identities = derive_identifiers(item, extra_ids)
        fingerprint = title_fingerprint(item.title, item.authors, item.year)
        async with self._db.session_factory() as session:
            paper = await _find_existing(session, identities, fingerprint)
            if paper is None:
                paper = _build_paper(item, identities, fingerprint)
                session.add(paper)
            else:
                merge_paper(paper, item, identities)
            await session.commit()
        return paper

    async def link_session(
        self,
        session_id: int,
        paper_id: int,
        *,
        rank: int = 0,
        score: float = 0.0,
        matched_keywords: list[str] | None = None,
    ) -> None:
        """把论文挂到一次检索会话上（重复调用会覆盖排序与分数）。"""
        payload = json.dumps(matched_keywords or [], ensure_ascii=False)
        async with self._db.session_factory() as session:
            link = await session.get(SearchSessionPaper, (session_id, paper_id))
            if link is None:
                session.add(
                    SearchSessionPaper(
                        session_id=session_id,
                        paper_id=paper_id,
                        rank=rank,
                        score=score,
                        matched_keywords_json=payload,
                    )
                )
            else:
                link.rank = rank
                link.score = score
                link.matched_keywords_json = payload
            await session.commit()

    async def list_papers(
        self,
        *,
        topic_id: int | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        source: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[Paper]]:
        """按主题、年份、来源、标题关键字分页查询论文实体。"""
        conditions = _paper_conditions(year_from, year_to, source, query)
        base = select(Paper)
        if topic_id is not None:
            base = base.join(PaperTopic, PaperTopic.paper_id == Paper.id).where(
                PaperTopic.topic_id == topic_id
            )
        async with self._db.session_factory() as session:
            total = (
                await session.execute(
                    select(func.count()).select_from(
                        base.where(*conditions).subquery()
                    )
                )
            ).scalar_one()
            statement = (
                base.where(*conditions)
                .order_by(Paper.citation_count.desc(), Paper.id.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = list((await session.execute(statement)).scalars().all())
        return int(total), rows

    async def get_paper(self, paper_id: int) -> Paper | None:
        async with self._db.session_factory() as session:
            return await session.get(Paper, paper_id)


def derive_identifiers(
    item: PaperItem,
    extra_ids: dict[str, str] | None = None,
) -> dict[str, str]:
    """汇总论文的各路标识。

    DOI 有三个来源：调用方显式传入、来源自带的 external_id（Crossref / DOAJ
    等来源的 external_id 就是 DOI）、URL。三处都按 DOI 形态校验，不会误判。
    """
    provided = extra_ids or {}
    return {
        "doi": normalize_doi(provided.get("doi"))
        or normalize_doi(item.external_id)
        or normalize_doi(item.url),
        "arxiv_id": normalize_arxiv_id(provided.get("arxiv_id"))
        or _source_external_id(item, "arxiv"),
        "s2_id": provided.get("s2_id", "") or _source_external_id(item, "s2"),
        "openalex_id": provided.get("openalex_id", "")
        or _source_external_id(item, "openalex"),
    }


def _source_external_id(item: PaperItem, source: str) -> str:
    if item.source == source and item.external_id:
        return item.external_id.strip()
    return ""


async def _find_existing(
    session: AsyncSession,
    identities: dict[str, str],
    fingerprint: str,
) -> Paper | None:
    for column in IDENTITY_COLUMNS:
        value = identities.get(column, "")
        if not value:
            continue
        found = await session.scalar(
            select(Paper).where(getattr(Paper, column) == value)
        )
        if found is not None:
            return found
    return await session.scalar(select(Paper).where(Paper.fingerprint == fingerprint))


def _build_paper(
    item: PaperItem,
    identities: dict[str, str],
    fingerprint: str,
) -> Paper:
    return Paper(
        doi=identities["doi"] or None,
        arxiv_id=identities["arxiv_id"] or None,
        s2_id=identities["s2_id"] or None,
        openalex_id=identities["openalex_id"] or None,
        title=item.title,
        normalized_title=normalize_title(item.title),
        fingerprint=fingerprint,
        abstract=item.abstract or "",
        authors_json=json.dumps(item.authors or [], ensure_ascii=False),
        year=item.year,
        citation_count=item.citation_count or 0,
        sources_json=json.dumps([item.source] if item.source else [], ensure_ascii=False),
        url=item.url or "",
        pdf_url=item.pdf_url or "",
    )


def merge_paper(
    paper: Paper,
    item: PaperItem,
    identities: dict[str, str],
) -> None:
    """把新来源的信息补进已有实体：标识补空、摘要取长、引用取大、来源取并集。"""
    for column in IDENTITY_COLUMNS:
        if not getattr(paper, column) and identities.get(column):
            setattr(paper, column, identities[column])
    if len(item.title or "") > len(paper.title or ""):
        paper.title = item.title
        paper.normalized_title = normalize_title(item.title)
    if len(item.abstract or "") > len(paper.abstract or ""):
        paper.abstract = item.abstract
    if item.year is not None and (paper.year is None or item.year < paper.year):
        paper.year = item.year
    if len(item.authors or []) > len(_json_list(paper.authors_json)):
        paper.authors_json = json.dumps(item.authors, ensure_ascii=False)
    if (item.citation_count or 0) > (paper.citation_count or 0):
        paper.citation_count = item.citation_count
    sources = _json_list(paper.sources_json)
    if item.source and item.source not in sources:
        sources.append(item.source)
        paper.sources_json = json.dumps(sources, ensure_ascii=False)
    if not paper.url and item.url:
        paper.url = item.url
    if not paper.pdf_url and item.pdf_url:
        paper.pdf_url = item.pdf_url


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _paper_conditions(
    year_from: int | None,
    year_to: int | None,
    source: str | None,
    query: str | None,
) -> list:
    """构造过滤条件；来源在 JSON 列里按子串匹配，SQLite 与 MySQL 通用。"""
    conditions = []
    if year_from is not None:
        conditions.append(Paper.year >= year_from)
    if year_to is not None:
        conditions.append(Paper.year <= year_to)
    if source:
        conditions.append(Paper.sources_json.like(f'%"{source}"%'))
    if query:
        conditions.append(Paper.title.like(f"%{query}%"))
    return conditions
