"""搜索缓存测试：写入、命中与过期。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.database import Database
from app.models.search_cache import SearchCache
from app.schemas.search import PaperItem
from app.services.cache_service import SearchCacheStore


def _item(title: str = "t") -> PaperItem:
    return PaperItem(title=title, source="arxiv", external_id="1", citation_count=3)


def test_build_key_is_stable():
    k1 = SearchCacheStore.build_key("arxiv", "LoRA", 10, 2024, 2024)
    k2 = SearchCacheStore.build_key("arxiv", "LoRA", 10, 2024, 2024)
    k3 = SearchCacheStore.build_key("arxiv", "LoRA", 5, 2024, 2024)
    assert k1 == k2
    assert k1 != k3


async def test_cache_roundtrip(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'cache.db').as_posix()}")
    await db.create_all()
    store = SearchCacheStore(db)
    key = SearchCacheStore.build_key("arxiv", "LoRA", 10, None, None)

    assert await store.get(key) is None
    await store.set(key, [_item()])
    items = await store.get(key)

    assert items is not None
    assert items[0].title == "t"
    assert items[0].citation_count == 3
    await db.close()


async def test_cache_expired(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'expired.db').as_posix()}")
    await db.create_all()
    store = SearchCacheStore(db)
    key = SearchCacheStore.build_key("arxiv", "LoRA", 10, None, None)
    await store.set(key, [_item()])

    async with db.session_factory() as session:
        row = (await session.execute(select(SearchCache))).scalar_one()
        row.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
        await session.commit()

    assert await store.get(key) is None
    await db.close()
