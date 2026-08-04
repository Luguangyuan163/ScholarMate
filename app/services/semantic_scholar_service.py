"""Semantic Scholar API 封装（P3 接入，提供引用量 citationCount）。"""

from __future__ import annotations

from app.schemas.search import PaperItem


class SemanticScholarService:
    async def search(self, query: str, limit: int = 10) -> list[PaperItem]:
        raise NotImplementedError("Semantic Scholar 将在 P3 接入")

    async def get_paper_detail(self, paper_id: str) -> dict:
        raise NotImplementedError("Semantic Scholar 论文详情将在 P3 接入")
