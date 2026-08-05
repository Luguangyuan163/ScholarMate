"""PDF 上传与本地语义检索接口测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz
import httpx
from fastapi.testclient import TestClient

import app.api.pdf as pdf_api
from app.main import create_app


class FailingPDFService:
    def extract(self, pdf_path):
        raise RuntimeError("extract boom")

    def chunk_paragraphs(self, text, max_chars=800):
        return [text]


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

    async def translate_paragraphs(self, paragraphs, target_lang="zh", batch_size=4):
        for offset, text in enumerate(paragraphs):
            self.calls.append(text)
            yield offset, f"[{target_lang}] {text}"


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


def test_upload_rejects_oversize_file(app_settings, tmp_path):
    pdf_path = tmp_path / "big.pdf"
    pdf_path.write_bytes(b"%PDF-1.7" + b"0" * (2 * 1024 * 1024))
    app = create_app(app_settings)
    with TestClient(app) as client:
        app.state.settings.max_upload_mb = 1
        with open(pdf_path, "rb") as handle:
            resp = client.post(
                "/api/pdf/upload",
                files={"file": ("big.pdf", handle, "application/pdf")},
            )
    assert resp.status_code == 413


def test_upload_rejects_pdf_like_content(app_settings, tmp_path):
    """魔数校验：仅后缀 .pdf 但内容不是 PDF 的文件应被拒绝。"""
    fake_path = tmp_path / "fake.pdf"
    fake_path.write_text("this is not a pdf", encoding="utf-8")
    app = create_app(app_settings)
    with TestClient(app) as client, open(fake_path, "rb") as handle:
        resp = client.post(
            "/api/pdf/upload",
            files={"file": ("fake.pdf", handle, "application/pdf")},
        )
    assert resp.status_code == 400


def test_upload_processing_failure_marks_failed(app_settings, tmp_path):
    pdf_path = tmp_path / "broken.pdf"
    _make_pdf(pdf_path, ["LoRA makes fine-tuning efficient."])
    app = create_app(app_settings)
    app.state.pdf_service = FailingPDFService()
    with TestClient(app) as client, open(pdf_path, "rb") as handle:
        resp = client.post(
            "/api/pdf/upload",
            files={"file": ("broken.pdf", handle, "application/pdf")},
        )
    assert resp.status_code == 500


def test_translate_pdf_not_ready_returns_409(app_settings, tmp_path):
    pdf_path = tmp_path / "pending.pdf"
    _make_pdf(pdf_path, ["Pending paper."])
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("pending.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]

        async def _mark_processing():
            async with app.state.database.session_factory() as session:
                from app.models.uploaded_pdf import UploadedPDF

                row = await session.get(UploadedPDF, pdf_id)
                row.status = "processing"
                await session.commit()

        import asyncio

        asyncio.run(_mark_processing())
        resp = client.post(f"/api/pdf/{pdf_id}/translate", json={"target_lang": "zh"})
    assert resp.status_code == 409


def test_translate_pdf_get_stream_endpoint(app_settings, tmp_path):
    """EventSource 使用的 GET 翻译流式端点。"""
    pdf_path = tmp_path / "stream.pdf"
    _make_multipage_pdf(
        pdf_path,
        [
            "First paragraph. " * 40,
            "Second paragraph. " * 40,
        ],
    )
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FakeTranslation()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("stream.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        resp = client.get(
            f"/api/pdf/{pdf_id}/translate-stream",
            params={"target_lang": "zh", "max_paragraphs": 1},
        )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: progress" in resp.text
    assert "event: segment" in resp.text
    assert "event: done" in resp.text


def test_translate_pdf_reports_llm_error(app_settings, tmp_path):
    class FailingTranslation:
        async def translate_paragraph(self, text, target_lang="zh"):
            raise RuntimeError("llm down")

        async def translate_paragraphs(self, paragraphs, target_lang="zh", batch_size=4):
            raise RuntimeError("llm down")

    pdf_path = tmp_path / "err.pdf"
    _make_multipage_pdf(
        pdf_path,
        [
            "First paragraph. " * 40,
            "Second paragraph. " * 40,
        ],
    )
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FailingTranslation()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("err.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        resp = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 2},
        )
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "翻译失败" in resp.text


def test_import_pdf_from_url_success(app_settings, tmp_path, monkeypatch):
    pdf_path = tmp_path / "remote.pdf"
    _make_pdf(pdf_path, ["Low-rank adaptation is efficient."])
    pdf_bytes = pdf_path.read_bytes()

    async def fake_download(url: str) -> bytes:
        return pdf_bytes

    monkeypatch.setattr(pdf_api, "_download_pdf", fake_download)
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()

    with TestClient(app) as client:
        resp = client.post(
            "/api/pdf/import-url",
            json={"url": "https://arxiv.org/pdf/2106.09685", "title": "LoRA"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"

    candidates = list(app.state.settings.pdf_upload_dir.glob("*.pdf"))
    assert len(candidates) == 1
    assert candidates[0].read_bytes().startswith(b"%PDF")

    with TestClient(app) as client:
        papers = client.get("/api/papers")
    assert papers.json()[0]["filename"] == "LoRA.pdf"


def test_import_pdf_from_url_rejects_non_pdf(app_settings, monkeypatch):
    async def fake_download(url: str) -> bytes:
        return b"this is not a pdf"

    monkeypatch.setattr(pdf_api, "_download_pdf", fake_download)
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post(
            "/api/pdf/import-url",
            json={"url": "https://example.com/not-a-pdf"},
        )
    assert resp.status_code == 400


def test_import_pdf_from_url_download_failure(app_settings, monkeypatch):
    async def fake_download(url: str) -> bytes:
        raise httpx.HTTPStatusError(
            "403",
            request=httpx.Request("GET", url),
            response=httpx.Response(403),
        )

    monkeypatch.setattr(pdf_api, "_download_pdf", fake_download)
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post(
            "/api/pdf/import-url",
            json={"url": "https://example.com/forbidden.pdf"},
        )
    assert resp.status_code == 502


def test_import_pdf_from_url_rejects_bad_scheme(app_settings, monkeypatch):
    async def fake_download(url: str) -> bytes:
        raise httpx.UnsupportedProtocol("file://")

    monkeypatch.setattr(pdf_api, "_download_pdf", fake_download)
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post(
            "/api/pdf/import-url",
            json={"url": "file:///C:/secret.pdf"},
        )
    assert resp.status_code == 400


def test_get_pdf_file_serves_inline(app_settings, tmp_path):
    pdf_path = tmp_path / "view.pdf"
    _make_pdf(pdf_path, ["Viewable paper."])
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("view.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        resp = client.get(f"/api/pdf/{pdf_id}/file")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "inline" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")


def test_get_pdf_file_missing_returns_404(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.get("/api/pdf/999/file")
    assert resp.status_code == 404
