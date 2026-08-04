"""Embedding 服务（P2 接入，默认 DashScope text-embedding-v3）。"""

from __future__ import annotations


class EmbeddingService:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Embedding 服务将在 P2 接入")
