"""PDF 上传与本地语义检索接口测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz
from fastapi.testclient import TestClient

from app.main import create_app


def _make_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line)
        y += 24
    doc.save(str(path))
    doc.close()


class FakeEmbeddings:
    async def create(self, **kwargs):
        n = len(kwargs["input"])
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * 8) for _ in range(n)])


class FakeEmbeddingService:
    def __init__(self) -> None:
        self._client = FakeEmbeddings()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.create(model="x", input=texts)
        return [item.embedding for item in response.data]


def test_upload_pdf_and_local_search(app_settings, tmp_path):
    pdf_path = tmp_path / "demo.pdf"
    _make_pdf(pdf_path, ["LoRA makes fine-tuning efficient."])
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()

    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            resp = client.post(
                "/api/pdf/upload",
                files={"file": ("demo.pdf", handle, "application/pdf")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        pdf_id = data["pdf_id"]

        search = client.post("/api/search", json={"query": "LoRA", "source": "local"})
        assert search.status_code == 200
        body = search.json()
        assert body["source"] == "local"
        assert body["total"] >= 1
        assert body["items"][0]["external_id"] == str(pdf_id)


def test_upload_rejects_non_pdf(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post(
            "/api/pdf/upload",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
    assert resp.status_code == 400


def test_papers_list_after_upload(app_settings, tmp_path):
    pdf_path = tmp_path / "list.pdf"
    _make_pdf(pdf_path, ["A paper about retrieval."])
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            resp = client.post(
                "/api/pdf/upload",
                files={"file": ("list.pdf", handle, "application/pdf")},
            )
        assert resp.status_code == 200
        papers = client.get("/api/papers")
        assert papers.status_code == 200
        assert len(papers.json()) == 1
        assert papers.json()[0]["filename"] == "list.pdf"
