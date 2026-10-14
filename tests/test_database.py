"""数据库模块测试：建表与迁移（旧链接论文表升级为论文实体表）。"""

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
    # v3.0 起 papers 是论文实体表（知识图谱的节点表），不再是旧的链接论文表
    assert "papers" in tables
    await db.close()


async def test_migration_replaces_legacy_papers_table(tmp_path):
    """旧版链接论文表在升级时被新版论文实体表取代，旧数据不残留。"""
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
        columns = {
            row[1]
            for row in (await conn.execute(text("PRAGMA table_info(papers)"))).all()
        }
        remaining = (
            await conn.execute(text("SELECT COUNT(*) FROM papers"))
        ).scalar_one()

    assert "papers" in tables
    assert "normalized_title" in columns
    assert "fingerprint" in columns
    assert "external_id" not in columns
    assert remaining == 0
    await db.close()
