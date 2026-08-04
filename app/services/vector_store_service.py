"""ChromaDB 封装（P2 接入，依赖按需导入）。"""

from __future__ import annotations


class VectorStoreService:
    async def add_document(self, paper_id: int, chunks: list[str]) -> None:
        raise NotImplementedError("向量存储将在 P2 接入")

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        raise NotImplementedError("向量检索将在 P2 接入")
