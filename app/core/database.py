"""数据库基础设施：异步引擎、会话工厂与依赖注入。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = create_async_engine(url)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        if url.startswith("sqlite"):
            event.listen(self.engine.sync_engine, "connect", _enable_sqlite_pragmas)
            _ensure_sqlite_parent(url)

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if self.url.startswith("sqlite"):
                await _migrate_sqlite(conn)

    async def close(self) -> None:
        await self.engine.dispose()


async def _migrate_sqlite(conn) -> None:
    """轻量兼容迁移：为旧库补齐新列（无 Alembic，逐列幂等检查）。"""
    _MIGRATIONS = [
        (
            "papers",
            "pdf_url",
            "ALTER TABLE papers ADD COLUMN pdf_url VARCHAR(500) NOT NULL DEFAULT ''",
        ),
    ]
    for table, column, ddl in _MIGRATIONS:
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
        if column not in {row[1] for row in rows}:
            await conn.execute(text(ddl))
    # 数据回填：旧 arXiv 收藏补 PDF 直链（幂等）
    await conn.execute(
        text(
            "UPDATE papers SET pdf_url = 'https://arxiv.org/pdf/' || external_id "
            "WHERE source = 'arxiv' AND pdf_url = ''"
        )
    )


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
