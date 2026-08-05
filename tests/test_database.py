"""数据库模块测试：建表与 Paper CRUD。"""

from __future__ import annotations

from sqlalchemy import select, text

from app.core.database import Database
from app.models.paper import Paper


async def test_paper_crud(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'crud.db').as_posix()}"
    db = Database(url)
    await db.create_all()

    async with db.session_factory() as session:
        session.add(
            Paper(
                title="LoRA: Low-Rank Adaptation of Large Language Models",
                authors='["Edward J. Hu"]',
                source="arxiv",
                external_id="2106.09685",
                year=2021,
            )
        )
        await session.commit()

    async with db.session_factory() as session:
        paper = (
            await session.execute(select(Paper).where(Paper.external_id == "2106.09685"))
        ).scalar_one()
        assert paper.title.startswith("LoRA")
        assert paper.year == 2021
        assert paper.citation_count == 0

    await db.close()


async def test_create_all_adds_pdf_url_to_legacy_papers_table(tmp_path):
    """旧版数据库（papers 表无 pdf_url 列）升级时自动补列。"""
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

    await db.create_all()

    async with db.engine.begin() as conn:
        columns = (await conn.execute(text("PRAGMA table_info(papers)"))).all()
    column_names = {row[1] for row in columns}
    assert "pdf_url" in column_names
    await db.close()


async def test_migration_backfills_arxiv_pdf_url(tmp_path):
    """迁移后，旧 arXiv 收藏自动补 PDF 直链。"""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'legacy2.db').as_posix()}"
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
                """
                INSERT INTO papers (title, source, external_id, url)
                VALUES ('Old LoRA', 'arxiv', '2405.00732v1', 'http://arxiv.org/abs/2405.00732v1')
                """
            )
        )

    await db.create_all()

    async with db.session_factory() as session:
        paper = (
            await session.execute(select(Paper).where(Paper.external_id == "2405.00732v1"))
        ).scalar_one()
    assert paper.pdf_url == "https://arxiv.org/pdf/2405.00732v1"
    await db.close()
