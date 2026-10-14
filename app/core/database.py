"""数据库基础设施：异步引擎、会话工厂与依赖注入。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

LEGACY_PAPERS_TABLE = "papers"
LEGACY_PAPERS_ENTITY_MARKER = "normalized_title"


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        self.engine = create_async_engine(url)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        if self.is_sqlite:
            event.listen(self.engine.sync_engine, "connect", _enable_sqlite_pragmas)
            _ensure_sqlite_parent(url)

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await _drop_legacy_link_papers_table(conn)
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()


async def _drop_legacy_link_papers_table(conn) -> None:
    """清理旧版「链接论文」表。

    旧表与新版论文实体表同名 ``papers``，因此在删除前先确认它缺少实体列
    ``normalized_title``；否则会把知识图谱的论文实体表一并删掉。
    """

    def _is_legacy_table(sync_conn) -> bool:
        inspector = inspect(sync_conn)
        if not inspector.has_table(LEGACY_PAPERS_TABLE):
            return False
        columns = {
            column["name"]
            for column in inspector.get_columns(LEGACY_PAPERS_TABLE)
        }
        return LEGACY_PAPERS_ENTITY_MARKER not in columns

    if await conn.run_sync(_is_legacy_table):
        await conn.execute(text(f"DROP TABLE IF EXISTS {LEGACY_PAPERS_TABLE}"))


def _enable_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _ensure_sqlite_parent(url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if url.startswith(prefix):
        path = Path(url.removeprefix(prefix))
        path.parent.mkdir(parents=True, exist_ok=True)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供请求级数据库会话。"""
    db: Database = request.app.state.database
    async with db.session_factory() as session:
        yield session
