"""Embedding 服务（DashScope text-embedding-v3，OpenAI 兼容端点）。

openai 依赖在首次调用时惰性导入。
"""

from __future__ import annotations

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

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            response = await self._get_client().embeddings.create(
                model=self.model, input=batch
            )
            vectors.extend(item.embedding for item in response.data)
        return vectors
