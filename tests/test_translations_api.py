"""翻译记录接口测试：翻译完成后持久化，支持列表/详情/删除。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


class FakeEmbeddingService:
    async def embed_texts(self, texts):
        return [[0.1] * 8 for _ in texts]


class FakeTranslation:
    async def translate_paragraph(self, text, target_lang="zh"):
        return f"[{target_lang}] {text}"

    async def translate_paragraphs(self, paragraphs, target_lang="zh", batch_size=4):
        for offset, text in enumerate(paragraphs):
            yield offset, f"[{target_lang}] {text}"


class RecordingTranslation(FakeTranslation):
    def __init__(self) -> None:
        self.calls = 0

    async def translate_paragraph(self, text, target_lang="zh"):
        self.calls += 1
        return f"[{target_lang}] {text}"

    async def translate_paragraphs(self, paragraphs, target_lang="zh", batch_size=4):
        for offset, text in enumerate(paragraphs):
            self.calls += 1
            yield offset, f"[{target_lang}] {text}"


def _upload_pdf(app, tmp_path, name="paper.pdf"):
    import fitz

    doc = fitz.open()
    for text in [
        "Low-rank adaptation reduces trainable parameters. " * 100,
        "This makes fine-tuning efficient. " * 100,
    ]:
        page = doc.new_page()
        y = 72
        for start in range(0, len(text), 60):
            page.insert_text((72, y), text[start : start + 60])
            y += 16
    pdf_path = tmp_path / name
    doc.save(str(pdf_path))
    doc.close()

    with TestClient(app) as client, open(pdf_path, "rb") as handle:
        uploaded = client.post(
            "/api/pdf/upload",
            files={"file": (name, handle, "application/pdf")},
        )
    return uploaded.json()["pdf_id"]


def test_translate_saves_record(app_settings, tmp_path):
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FakeTranslation()
    pdf_id = _upload_pdf(app, tmp_path)

    with TestClient(app) as client:
        resp = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 0},
        )
        assert resp.status_code == 200
        assert "event: done" in resp.text

        records = client.get("/api/translations").json()
        assert len(records) == 1
        record = records[0]
        assert record["pdf_id"] == pdf_id
        assert record["filename"] == "paper.pdf"
        assert record["total"] > 0

        detail = client.get(f"/api/translations/{record['id']}").json()
        assert len(detail["segments"]) == record["total"]
        assert detail["segments"][0]["translation"].startswith("[zh] ")


def test_translations_list_empty_on_fresh_db(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        assert client.get("/api/translations").json() == []


def test_get_translation_not_found(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        assert client.get("/api/translations/999").status_code == 404


def test_delete_translation(app_settings, tmp_path):
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FakeTranslation()
    pdf_id = _upload_pdf(app, tmp_path)

    with TestClient(app) as client:
        client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 0},
        )
        record_id = client.get("/api/translations").json()[0]["id"]
        deleted = client.delete(f"/api/translations/{record_id}")
        assert deleted.status_code == 200
        assert client.get("/api/translations").json() == []


def test_translate_error_does_not_save_record(app_settings, tmp_path):
    class FailingTranslation:
        async def translate_paragraph(self, text, target_lang="zh"):
            raise RuntimeError("llm down")

    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FailingTranslation()
    pdf_id = _upload_pdf(app, tmp_path)

    with TestClient(app) as client:
        resp = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 0},
        )
        assert "event: error" in resp.text
        assert client.get("/api/translations").json() == []


def test_delete_pdf_cascades_translation_records(app_settings, tmp_path):
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = FakeTranslation()
    pdf_id = _upload_pdf(app, tmp_path)

    with TestClient(app) as client:
        client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 0},
        )
        assert len(client.get("/api/translations").json()) == 1
        client.delete(f"/api/papers/{pdf_id}")
        assert client.get("/api/translations").json() == []


def test_retranslate_reuses_cached_segments(app_settings, tmp_path):
    """断点续翻：已翻译段落复用缓存，不重复调用大模型。"""
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = RecordingTranslation()
    pdf_id = _upload_pdf(app, tmp_path)

    with TestClient(app) as client:
        first = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 1},
        )
        assert first.status_code == 200
        calls_after_first = app.state.translation_service.calls

        second = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 0},
        )
        assert second.status_code == 200
        total = second.text.count("event: segment")
        calls_after_second = app.state.translation_service.calls
        assert total > 1
        assert calls_after_second - calls_after_first == total - 1


def test_retranslate_full_cache_skips_llm(app_settings, tmp_path):
    """全量缓存时再次翻译不产生任何 LLM 调用。"""
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()
    app.state.translation_service = RecordingTranslation()
    pdf_id = _upload_pdf(app, tmp_path)

    with TestClient(app) as client:
        first = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 0},
        )
        calls_after_first = app.state.translation_service.calls
        assert calls_after_first >= 1

        second = client.post(
            f"/api/pdf/{pdf_id}/translate",
            json={"target_lang": "zh", "max_paragraphs": 0},
        )
        assert second.status_code == 200
        assert app.state.translation_service.calls == calls_after_first
        assert second.text.count("event: segment") == first.text.count(
            "event: segment"
        )
        assert len(client.get("/api/translations").json()) == 2
