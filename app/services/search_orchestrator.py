"""多关键词检索编排：查询生成 → 多源并行 → 归一去重 → 打分 → 落库。

对应设计文档第 5 节。一次检索产生一条 `search_sessions` 记录，
命中论文经 `PaperStore` 归一去重后挂到该会话上。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import combinations

from app.core.database import Database
from app.models.paper import SearchSession
from app.schemas.search import (
    MergedPaperItem,
    PaperItem,
    SearchRunRequest,
    SearchRunResponse,
)
from app.services.paper_identity import title_fingerprint
from app.services.paper_source import SourceRegistry
from app.services.paper_store import IDENTITY_COLUMNS, PaperStore, derive_identifiers

MAX_QUERIES = 8
CITATION_NORM_CAP = 1000.0
RECENCY_WINDOW_YEARS = 10.0
SOURCE_COUNT_CAP = 3.0
WEIGHTS = {"keyword": 0.45, "citation": 0.25, "recency": 0.20, "sources": 0.10}


@dataclass
class MergedCandidate:
    """归一去重后的候选论文。"""

    items: list[PaperItem] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    keywords: set[str] = field(default_factory=set)

    @property
    def primary(self) -> PaperItem:
        return max(self.items, key=lambda item: len(item.abstract or ""))


class SearchOrchestrator:
    """把一次多关键词检索拆成查询、并行执行、合并与落库。"""

    def __init__(
        self,
        registry: SourceRegistry,
        store: PaperStore,
        db: Database,
    ) -> None:
        self._registry = registry
        self._store = store
        self._db = db

    async def run(self, request: SearchRunRequest) -> SearchRunResponse:
        keywords = normalize_keywords(request.keywords)
        source_keys: dict[str, set[str]] = {}
        failed: list[str] = []
        candidates: dict[str, MergedCandidate] = {}

        for query in build_queries(keywords):
            results = await self._registry.search(
                query,
                request.sources,
                request.per_source,
                year_from=request.year_from,
                year_to=request.year_to,
            )
            for result in results:
                if result.failed:
                    if result.name not in failed:
                        failed.append(result.name)
                    continue
                bucket = source_keys.setdefault(result.name, set())
                bucket.update(candidates_from_key(item) for item in result.items)
                collect_candidates(candidates, result.items, query, keywords)

        # 分来源统计去重后的命中数：同一条查询里重复出现的论文只算一次
        by_source = {name: len(keys) for name, keys in source_keys.items()}
        ranked = rank_candidates(candidates, keywords)
        session_id = await self._persist(request, ranked, failed)
        items = await self._attach_papers(session_id, ranked)
        return SearchRunResponse(
            session_id=session_id,
            total=sum(by_source.values()),
            merged=len(items),
            by_source=by_source,
            failed_sources=failed,
            items=items,
        )

    async def _persist(
        self,
        request: SearchRunRequest,
        ranked: list[tuple[MergedCandidate, float]],
        failed: list[str],
    ) -> int:
        async with self._db.session_factory() as session:
            row = SearchSession(
                keywords_json=json.dumps(
                    normalize_keywords(request.keywords), ensure_ascii=False
                ),
                sources_json=json.dumps(request.sources, ensure_ascii=False),
                year_from=request.year_from,
                year_to=request.year_to,
                status="done",
                result_count=len(ranked),
                failed_sources=json.dumps(failed, ensure_ascii=False),
            )
            session.add(row)
            await session.commit()
            return row.id

    async def _attach_papers(
        self,
        session_id: int,
        ranked: list[tuple[MergedCandidate, float]],
    ) -> list[MergedPaperItem]:
        items = []
        for rank, (candidate, score) in enumerate(ranked):
            paper = await self._upsert_candidate(candidate)
            keywords = sorted(candidate.keywords)
            await self._store.link_session(
                session_id,
                paper.id,
                rank=rank,
                score=score,
                matched_keywords=keywords,
            )
            items.append(
                MergedPaperItem(
                    paper_id=paper.id,
                    title=paper.title,
                    authors=json.loads(paper.authors_json or "[]"),
                    year=paper.year,
                    citation_count=paper.citation_count,
                    sources=sorted(json.loads(paper.sources_json or "[]")),
                    matched_keywords=keywords,
                    score=score,
                    url=paper.url,
                    pdf_url=paper.pdf_url,
                )
            )
        return items

    async def _upsert_candidate(self, candidate: MergedCandidate):
        paper = None
        for item in candidate.items:
            paper = await self._store.upsert(item)
        if paper is None:
            raise ValueError("候选论文为空，无法入库")
        return paper


def normalize_keywords(keywords: list[str]) -> list[str]:
    """去空白、去重（大小写不敏感）、保持输入顺序。"""
    seen: set[str] = set()
    normalized = []
    for keyword in keywords:
        cleaned = " ".join(str(keyword).split())
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        normalized.append(cleaned)
    return normalized


def build_queries(keywords: list[str], max_queries: int = MAX_QUERIES) -> list[str]:
    """单词查询保证召回，两两组合发现交叉方向，最后补一条全体合取。"""
    queries = list(keywords)
    for first, second in combinations(keywords, 2):
        if len(queries) >= max_queries:
            break
        queries.append(f"{first} {second}")
    combined = " ".join(keywords)
    if len(keywords) > 1 and len(queries) < max_queries and combined not in queries:
        queries.append(combined)
    return queries[:max_queries]


def candidates_from_key(item: PaperItem) -> str:
    """归一键：优先标识字段，其次标题指纹。"""
    identities = derive_identifiers(item)
    for column in IDENTITY_COLUMNS:
        if identities.get(column):
            return f"{column}:{identities[column]}"
    return "fingerprint:" + title_fingerprint(item.title, item.authors, item.year)


def collect_candidates(
    candidates: dict[str, MergedCandidate],
    items: list[PaperItem],
    query: str,
    keywords: list[str],
) -> None:
    """把一次查询的结果并入候选集合，记录来源与命中的关键词。"""
    matched = {keyword for keyword in keywords if keyword.lower() in query.lower()}
    for item in items:
        if not item.title:
            continue
        key = candidates_from_key(item)
        candidate = candidates.setdefault(key, MergedCandidate())
        candidate.items.append(item)
        candidate.sources.add(item.source)
        candidate.keywords.update(matched)


def score_candidate(
    candidate: MergedCandidate,
    keywords: list[str],
    current_year: int,
) -> float:
    """四项加权打分，权重见设计文档 5.3 节。"""
    primary = candidate.primary
    keyword_ratio = len(candidate.keywords) / len(keywords) if keywords else 0.0
    citation = min(
        math.log1p(max(primary.citation_count, 0)) / math.log1p(CITATION_NORM_CAP), 1.0
    )
    if primary.year is None:
        recency = 0.0
    else:
        age = max(current_year - primary.year, 0)
        recency = max(1.0 - age / RECENCY_WINDOW_YEARS, 0.0)
    source_score = min(len(candidate.sources) / SOURCE_COUNT_CAP, 1.0)
    score = (
        WEIGHTS["keyword"] * keyword_ratio
        + WEIGHTS["citation"] * citation
        + WEIGHTS["recency"] * recency
        + WEIGHTS["sources"] * source_score
    )
    return round(score, 4)


def rank_candidates(
    candidates: dict[str, MergedCandidate],
    keywords: list[str],
    current_year: int | None = None,
) -> list[tuple[MergedCandidate, float]]:
    year = current_year or datetime.now(UTC).year
    scored = [
        (candidate, score_candidate(candidate, keywords, year))
        for candidate in candidates.values()
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored
