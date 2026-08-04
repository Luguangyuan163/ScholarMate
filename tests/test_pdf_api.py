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


def _make_multipage_pdf(path: Path, pages: list[str]) -> None:
    """每页一段长文本（自动换行插入），段落超过分块阈值时独立成块。"""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        y = 72
        for line in _wrap(text, 60):
            page.insert_text((72, y), line)
            y += 16
    doc.save(str(path))
    doc.close()


def _wrap(text: str, width: int) -> list[str]:
    return [text[i : i + width] for i in range(0, len(text), width)]


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


class FakeTranslation:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def translate_paragraph(self, text: str, target_lang: str = "zh") -> str:
        self.calls.append(text)
        return f"[{target_lang}] {text}"


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


def test_translate_pdf_streams_segments(app_settings, tmp_path):
    pdf_path = tmp_path / "translate.pdf"
    _make_multipage_pdf(
        pdf_path,
        [
            "Low-rank adaptation reduces trainable parameters. " * 40,
            "This makes fine-tuning large models efficient. " * 40,
        ],
    )
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FakeTranslation()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("translate.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        resp = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 0},
        )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: progress" in resp.text
    assert "event: segment" in resp.text
    assert "[zh] Low-rank adaptation reduces" in resp.text
    assert "event: done" in resp.text
    assert len(app.state.translation_service.calls) == 2


def test_translate_pdf_limits_paragraphs(app_settings, tmp_path):
    pdf_path = tmp_path / "limit.pdf"
    _make_multipage_pdf(
        pdf_path,
        [
            "First paragraph. " * 40,
            "Second paragraph. " * 40,
            "Third paragraph. " * 40,
        ],
    )
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FakeTranslation()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("limit.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        resp = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 1},
        )
    assert resp.status_code == 200
    assert resp.text.count("event: segment") == 1
    assert "event: done" in resp.text
    assert len(app.state.translation_service.calls) == 1


def test_translate_pdf_not_found_returns_404(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post(
            "/api/pdf/999/translate",
            json={"target_lang": "zh"},
        )
    assert resp.status_code == 404
