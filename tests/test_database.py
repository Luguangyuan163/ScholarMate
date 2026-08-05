"""数据库模块测试：建表与迁移（本地论文库只保留本地 PDF）。"""

from __future__ import annotations

from sqlalchemy import text

from app.core.database import Database


async def test_create_all_creates_uploaded_pdfs_table(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'tables.db').as_posix()}"
    db = Database(url)
    await db.create_all()

    async with db.engine.begin() as conn:
        tables = {
            row[0]
            for row in (
                await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            ).all()
        }
    assert "uploaded_pdfs" in tables
    assert "papers" not in tables
    await db.close()


async def test_migration_drops_legacy_papers_table(tmp_path):
    """旧版数据库中的链接论文表（papers）在升级时被移除。"""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    db = Database(url)
    async with db.engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE papers (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR(500) NOT NULL,
                    authors TEXT NOT NULL DEFAULT '[]',
                    abstract TEXT NOT NULL DEFAULT '',
                    source VARCHAR(32) NOT NULL,
                    external_id VARCHAR(128) NOT NULL,
                    year INTEGER,
                    citation_count INTEGER NOT NULL DEFAULT 0,
                    url VARCHAR(500) NOT NULL DEFAULT '',
                    created_at DATETIME
                )
                """
            )
        )
        await conn.execute(
            text(
                "INSERT INTO papers (title, source, external_id, url) "
                "VALUES ('Old Link Paper', 'arxiv', '2405.00732', 'http://example.com')"
            )
        )

    await db.create_all()

    async with db.engine.begin() as conn:
        tables = {
            row[0]
            for row in (
                await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            ).all()
        }
    assert "papers" not in tables
    await db.close()
