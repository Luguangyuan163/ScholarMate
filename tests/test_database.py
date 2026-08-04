"""数据库模块测试：建表与 Paper CRUD。"""

from __future__ import annotations

from sqlalchemy import select

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
