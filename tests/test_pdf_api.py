"""PDF 上传与本地语义检索接口测试。"""

from __future__ import annotations

import asyncio
import threading
import time
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

    async def embed_texts(self, texts: list[str], on_batch=None) -> list[list[float]]:
        response = await self._client.create(model="x", input=texts)
        if on_batch is not None:
            on_batch(len(texts), len(texts))
        return [item.embedding for item in response.data]


class BlockingEmbeddingService:
    """向量化阻塞在 release 事件上，用于验证上传接口立即返回、后台异步处理。"""

    def __init__(self) -> None:
        self.release = threading.Event()

    async def embed_texts(self, texts, on_batch=None):
        await asyncio.to_thread(self.release.wait, 5)
        if on_batch is not None:
            on_batch(len(texts), len(texts))
        return [[0.1] * 8 for _ in texts]


def _wait_pdf_status(client, pdf_id: int, expected: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/pdf/{pdf_id}/status")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] == expected:
            return body
        time.sleep(0.05)
    raise AssertionError(f"pdf {pdf_id} 未在 {timeout}s 内变为 {expected}")


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

    async def translate_paragraphs_concurrent(
        self, paragraphs, target_lang="zh", max_concurrency=4
    ):
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
        assert data["status"] == "processing"
        pdf_id = data["pdf_id"]
        _wait_pdf_status(client, pdf_id, "ready")

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
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        failed = _wait_pdf_status(client, data["pdf_id"], "failed")
        assert failed["stage"] == "failed"
        papers = client.get("/api/papers").json()
        assert papers[0]["status"] == "failed"


def test_upload_returns_processing_and_background_becomes_ready(app_settings, tmp_path):
    """上传接口立即返回 processing；提取/向量化在后台完成，/status 可查询进度。"""
    pdf_path = tmp_path / "async.pdf"
    _make_pdf(pdf_path, ["Async upload paper."])
    app = create_app(app_settings)
    embedding = BlockingEmbeddingService()
    app.state.embedding_service = embedding
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            resp = client.post(
                "/api/pdf/upload",
                files={"file": ("async.pdf", handle, "application/pdf")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        pdf_id = data["pdf_id"]

        status = client.get(f"/api/pdf/{pdf_id}/status").json()
        assert status["status"] == "processing"
        assert status["stage"] in {"extracting", "embedding"}

        embedding.release.set()
        ready = _wait_pdf_status(client, pdf_id, "ready")
        assert ready["stage"] == "done"
        papers = client.get("/api/papers").json()
        assert papers[0]["status"] == "ready"


def test_pdf_status_not_found_returns_404(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        assert client.get("/api/pdf/999/status").status_code == 404


def test_translate_pdf_allowed_during_processing(app_settings, tmp_path):
    """上传后立即可以开始翻译，不必等向量化完成。"""
    pdf_path = tmp_path / "pending.pdf"
    _make_multipage_pdf(
        pdf_path,
        [
            "Low-rank adaptation reduces trainable parameters. " * 40,
            "This makes fine-tuning large models efficient. " * 40,
        ],
    )
    app = create_app(app_settings)
    embedding = BlockingEmbeddingService()
    app.state.embedding_service = embedding
    app.state.translation_service = FakeTranslation()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("pending.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        resp = client.post(f"/api/pdf/{pdf_id}/translate", json={"target_lang": "zh"})
        assert resp.status_code == 200
        assert "event: segment" in resp.text
        assert "event: done" in resp.text
        embedding.release.set()


def test_translate_pdf_failed_returns_409(app_settings, tmp_path):
    pdf_path = tmp_path / "failed.pdf"
    _make_pdf(pdf_path, ["Failed paper."])
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("failed.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]

        async def _mark_failed():
            async with app.state.database.session_factory() as session:
                from app.models.uploaded_pdf import UploadedPDF

                row = await session.get(UploadedPDF, pdf_id)
                row.status = "failed"
                await session.commit()

        import asyncio

        asyncio.run(_mark_failed())
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


def _make_layout_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(
        fitz.Rect(72, 60, 500, 160),
        "Low-Rank Adaptation (LoRA) reduces trainable parameters.",
        fontsize=11,
    )
    page.insert_textbox(
        fitz.Rect(72, 180, 500, 220),
        "This second paragraph is short.",
        fontsize=11,
    )
    doc.save(str(path))
    doc.close()


def test_translate_pdf_layout_stream_emits_bbox_segments(app_settings, tmp_path):
    """mode=layout：segment 携带页号、bbox、页面尺寸与自适应字号。"""
    pdf_path = tmp_path / "layout_stream.pdf"
    _make_layout_pdf(pdf_path)
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FakeTranslation()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("layout_stream.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        resp = client.get(
            f"/api/pdf/{pdf_id}/translate-stream",
            params={"target_lang": "zh", "mode": "layout"},
        )
    assert resp.status_code == 200
    assert "event: layout" in resp.text
    assert '"pages"' in resp.text
    assert '"bbox"' in resp.text
    assert '"page_width"' in resp.text
    assert '"page_height"' in resp.text
    assert '"font_size"' in resp.text
    assert resp.text.count("event: segment") == 2
    assert "event: done" in resp.text


def test_translate_pdf_layout_reuses_cache_on_rerun(app_settings, tmp_path):
    """版面对照翻译再次执行时复用已保存段落缓存，不再调用 LLM。"""
    pdf_path = tmp_path / "layout_cache.pdf"
    _make_layout_pdf(pdf_path)
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    translation = FakeTranslation()
    app.state.translation_service = translation
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("layout_cache.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        first = client.get(
            f"/api/pdf/{pdf_id}/translate-stream",
            params={"target_lang": "zh", "mode": "layout"},
        )
        assert first.status_code == 200
        calls_after_first = len(translation.calls)
        assert calls_after_first == 2

        second = client.get(
            f"/api/pdf/{pdf_id}/translate-stream",
            params={"target_lang": "zh", "mode": "layout"},
        )
    assert second.status_code == 200
    assert second.text.count("event: segment") == 2
    assert len(translation.calls) == calls_after_first


def test_translate_pdf_layout_respects_max_paragraphs(app_settings, tmp_path):
    pdf_path = tmp_path / "layout_limit.pdf"
    _make_layout_pdf(pdf_path)
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FakeTranslation()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("layout_limit.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        resp = client.get(
            f"/api/pdf/{pdf_id}/translate-stream",
            params={"target_lang": "zh", "mode": "layout", "max_paragraphs": 1},
        )
    assert resp.status_code == 200
    assert resp.text.count("event: segment") == 1


def test_translate_pdf_reports_llm_error(app_settings, tmp_path):
    class FailingTranslation:
        async def translate_paragraph(self, text, target_lang="zh"):
            raise RuntimeError("llm down")

        async def translate_paragraphs(self, paragraphs, target_lang="zh", batch_size=4):
            raise RuntimeError("llm down")

        async def translate_paragraphs_concurrent(
            self, paragraphs, target_lang="zh", max_concurrency=4
        ):
            raise RuntimeError("llm down")
            yield  # noqa: B012 使方法成为异步生成器，供 async for 迭代

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


def test_translate_pdf_emits_heartbeat_status(app_settings, tmp_path, monkeypatch):
    """翻译等待期间每 N 秒发 status 心跳，避免长时间无输出。"""

    class SlowTranslation:
        async def translate_paragraph(self, text, target_lang="zh"):
            await asyncio.sleep(0.3)
            return f"[{target_lang}] {text}"

        async def translate_paragraphs(self, paragraphs, target_lang="zh", batch_size=4):
            for offset, text in enumerate(paragraphs):
                yield offset, f"[{target_lang}] {text}"

        async def translate_paragraphs_concurrent(
            self, paragraphs, target_lang="zh", max_concurrency=4
        ):
            for offset, text in enumerate(paragraphs):
                await asyncio.sleep(0.3)
                yield offset, f"[{target_lang}] {text}"

    monkeypatch.setattr(pdf_api, "TRANSLATE_HEARTBEAT_SECONDS", 0.05)
    pdf_path = tmp_path / "heartbeat.pdf"
    _make_multipage_pdf(
        pdf_path,
        [
            "First paragraph. " * 40,
            "Second paragraph. " * 40,
        ],
    )
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = SlowTranslation()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("heartbeat.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        resp = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 2},
        )
    assert resp.status_code == 200
    assert "event: status" in resp.text
    assert "正在翻译" in resp.text


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
        assert data["status"] == "processing"
        _wait_pdf_status(client, data["pdf_id"], "ready")

        candidates = list(app.state.settings.pdf_upload_dir.glob("*.pdf"))
        assert len(candidates) == 1
        assert candidates[0].read_bytes().startswith(b"%PDF")
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


def test_get_pdf_page_image(app_settings, tmp_path):
    """原文预览：按页渲染 PDF 为 PNG，保留原始排版供对照阅读。"""
    pdf_path = tmp_path / "pages.pdf"
    _make_multipage_pdf(
        pdf_path,
        [
            "First page content with layout. " * 60,
            "Second page content with layout. " * 60,
        ],
    )
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("pages.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]

        resp = client.get(f"/api/pdf/{pdf_id}/pages/1/image")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content.startswith(b"\x89PNG")
        assert resp.headers.get("x-total-pages") == "2"

        out_of_range = client.get(f"/api/pdf/{pdf_id}/pages/99/image")
        assert out_of_range.status_code == 404

        missing = client.get("/api/pdf/999/pages/1/image")
        assert missing.status_code == 404


def test_translate_skips_figure_and_table_text(app_settings, tmp_path):
    """翻译不包含图表区域文字：图片内文字与表格单元格被过滤。"""
    pdf_path = tmp_path / "figtable.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Body paragraph that should be translated.")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 120))
    pix.set_rect(fitz.IRect(0, 0, 200, 120), (230, 230, 230))
    page.insert_image(fitz.Rect(72, 150, 400, 300), pixmap=pix)
    page.insert_text((100, 200), "Axis label inside figure")
    page.insert_text((72, 330), "Figure 1: caption below figure.")
    x0, y0 = 72, 400
    for i in range(3):
        for j in range(2):
            rect = fitz.Rect(
                x0 + j * 120, y0 + i * 40, x0 + (j + 1) * 120, y0 + (i + 1) * 40
            )
            page.draw_rect(rect, color=(0, 0, 0), width=0.7)
    page.insert_text((x0 + 10, y0 + 25), "Cell A")
    page.insert_text((x0 + 130, y0 + 25), "Cell B")
    page.insert_text((x0 + 10, y0 + 65), "Cell C")
    doc.save(str(pdf_path))
    doc.close()

    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FakeTranslation()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as handle:
            uploaded = client.post(
                "/api/pdf/upload",
                files={"file": ("figtable.pdf", handle, "application/pdf")},
            )
        pdf_id = uploaded.json()["pdf_id"]
        resp = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 0},
        )
    assert resp.status_code == 200
    assert "Body paragraph" in resp.text
    assert "Figure 1" in resp.text
    assert "Axis label inside figure" not in resp.text
    assert "Cell A" not in resp.text
