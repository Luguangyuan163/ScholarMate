"""Embedding 服务（DashScope text-embedding-v3，OpenAI 兼容端点）。

openai 依赖在首次调用时惰性导入。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

DASHSCOPE_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
BATCH_SIZE = 10  # DashScope 单次调用上限


@dataclass
class EmbeddingService:
    api_key: str
    model: str = "text-embedding-v3"
    base_url: str = DASHSCOPE_EMBEDDING_BASE_URL
    _client: object | None = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    async def embed_texts(
        self,
        texts: list[str],
        on_batch: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        """分批向量化；每完成一批调用 on_batch(已完成条数, 总批数) 上报进度。"""
        vectors: list[list[float]] = []
        total = len(texts)
        done = 0
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            response = await self._get_client().embeddings.create(
                model=self.model, input=batch
            )
            vectors.extend(item.embedding for item in response.data)
            done += len(batch)
            if on_batch is not None:
                on_batch(done, total)
        return vectors
