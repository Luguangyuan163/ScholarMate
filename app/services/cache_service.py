"""搜索结果 24h 缓存（SQLite 持久化）。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.database import Database
from app.models.search_cache import SearchCache
from app.schemas.search import PaperItem

CACHE_TTL_SECONDS = 86400


class SearchCacheStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def build_key(
        source: str,
        query: str,
        max_results: int,
        year_from: int | None,
        year_to: int | None,
    ) -> str:
        raw = json.dumps(
            {
                "source": source,
                "query": query,
                "max_results": max_results,
                "year_from": year_from,
                "year_to": year_to,
            },
            sort_keys=True,
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    async def get(self, cache_key: str) -> list[PaperItem] | None:
        cutoff = _now_naive() - timedelta(seconds=CACHE_TTL_SECONDS)
        async with self._db.session_factory() as session:
            row = await session.scalar(
                select(SearchCache).where(
                    SearchCache.cache_key == cache_key,
                    SearchCache.created_at >= cutoff,
                )
            )
            if row is None:
                return None
            payload = json.loads(row.response_json)
        return [PaperItem.model_validate(item) for item in payload]

    async def set(self, cache_key: str, items: list[PaperItem]) -> None:
        payload = json.dumps(
            [item.model_dump(mode="json") for item in items],
            ensure_ascii=False,
        )
        cutoff = _now_naive() - timedelta(seconds=CACHE_TTL_SECONDS)
        async with self._db.session_factory() as session:
            session.add(SearchCache(cache_key=cache_key, response_json=payload))
            await session.execute(delete(SearchCache).where(SearchCache.created_at < cutoff))
            await session.commit()


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
