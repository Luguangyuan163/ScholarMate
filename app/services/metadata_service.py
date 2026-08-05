"""元数据源回退：优先 S2（配置了 key），失败或无 key 时回退 OpenAlex。"""

from __future__ import annotations

import httpx

from app.schemas.search import PaperItem


class FallbackMetadataSource:
    def __init__(self, s2, openalex, prefer_s2: bool = False) -> None:
        self._s2 = s2
        self._openalex = openalex
        self._prefer_s2 = prefer_s2

    async def search(
        self,
        query: str,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[PaperItem]:
        if self._prefer_s2:
            try:
                return await self._s2.search(
                    query, limit=limit, year_from=year_from, year_to=year_to
                )
            except httpx.HTTPError:
                pass
        return await self._openalex.search(
            query, limit=limit, year_from=year_from, year_to=year_to
        )

    async def get_paper_detail(self, paper_id: str) -> dict:
        if self._prefer_s2:
            try:
                return await self._s2.get_paper_detail(paper_id)
            except httpx.HTTPError:
                pass
        return await self._openalex.get_paper_detail(paper_id)
