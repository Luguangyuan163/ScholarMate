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


def _upload_pdf(app, tmp_path, name="paper.pdf"):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Low-rank adaptation reduces parameters. ")
    page.insert_text((72, 96), "This makes fine-tuning efficient. ")
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
