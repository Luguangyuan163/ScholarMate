"""Embedding 服务测试（openai 客户端使用替身）。"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.embedding_service import EmbeddingService


class FakeEmbeddings:
    def __init__(self) -> None:
        self.last_kwargs = None
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        self.calls.append(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(embedding=[0.1, 0.2, 0.3]) for _ in kwargs["input"]
            ]
        )


class FakeClient:
    def __init__(self) -> None:
        self.embeddings = FakeEmbeddings()


async def test_embed_texts_returns_vectors():
    client = FakeClient()
    service = EmbeddingService(api_key="k", model="text-embedding-v3", _client=client)
    vectors = await service.embed_texts(["a", "b"])
    assert len(vectors) == 2
    assert vectors[0] == [0.1, 0.2, 0.3]
    assert client.embeddings.last_kwargs["model"] == "text-embedding-v3"


async def test_embed_texts_batches_at_10():
    client = FakeClient()
    service = EmbeddingService(api_key="k", model="text-embedding-v3", _client=client)
    vectors = await service.embed_texts([f"text-{index}" for index in range(25)])
    assert len(vectors) == 25
    assert len(client.embeddings.calls) == 3
    assert all(len(call["input"]) <= 10 for call in client.embeddings.calls)


async def test_embed_texts_reports_batch_progress():
    """每完成一批调用 on_batch(done, total)，用于上传后台任务展示向量化进度。"""
    client = FakeClient()
    service = EmbeddingService(api_key="k", model="text-embedding-v3", _client=client)
    progress: list[tuple[int, int]] = []
    vectors = await service.embed_texts(
        [f"text-{index}" for index in range(25)],
        on_batch=lambda done, total: progress.append((done, total)),
    )
    assert len(vectors) == 25
    assert progress == [(10, 25), (20, 25), (25, 25)]
