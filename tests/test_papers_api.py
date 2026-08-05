"""论文库管理接口测试：本地 PDF 入库（自动下载）、单项/批量删除与路径防护。"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import fitz
import httpx
from fastapi.testclient import TestClient

import app.api.papers as papers_api
from app.main import create_app
from app.models.uploaded_pdf import UploadedPDF


def _insert_paper(app, **kwargs) -> int:
    """直接向数据库插入一条论文记录，返回 pdf_id。"""
    defaults = {
        "filename": "seed.pdf",
        "original_name": "seed.pdf",
        "file_path": "unused.pdf",
        "status": "ready",
    }
    defaults.update(kwargs)

    async def _insert() -> int:
        async with app.state.database.session_factory() as session:
            row = UploadedPDF(**defaults)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id

    return asyncio.run(_insert())


def _make_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "LoRA paper.")
    data = doc.tobytes()
    doc.close()
    return data


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


def _wait_pdf_status(client, pdf_id: int, expected: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/pdf/{pdf_id}/status").json()
        if body["status"] == expected:
            return body
        time.sleep(0.05)
    raise AssertionError(f"pdf {pdf_id} 未在 {timeout}s 内变为 {expected}")


def test_delete_paper_removes_row_and_file(app_settings, tmp_path):
    app = create_app(app_settings)

    with TestClient(app) as client:
        upload_dir = app.state.settings.pdf_upload_dir
        upload_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = upload_dir / "victim.pdf"
        pdf_path.write_bytes(b"%PDF-1.7 fake")
        pdf_id = _insert_paper(app, file_path=str(pdf_path))
        resp = client.delete(f"/api/papers/{pdf_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": pdf_id}
    assert not pdf_path.exists()


def test_delete_missing_paper_returns_404(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.delete("/api/papers/999")
    assert resp.status_code == 404


def test_delete_rejects_path_outside_upload_dir(app_settings, tmp_path):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.7 fake")
    app = create_app(app_settings)

    with TestClient(app) as client:
        pdf_id = _insert_paper(app, file_path=str(outside))
        resp = client.delete(f"/api/papers/{pdf_id}")
    assert resp.status_code == 400
    assert outside.exists()


def test_batch_delete_removes_rows_and_files(app_settings):
    app = create_app(app_settings)

    with TestClient(app) as client:
        upload_dir = app.state.settings.pdf_upload_dir
        upload_dir.mkdir(parents=True, exist_ok=True)
        ids = []
        for index in range(3):
            pdf_path = upload_dir / f"batch{index}.pdf"
            pdf_path.write_bytes(b"%PDF-1.7 fake")
            ids.append(
                _insert_paper(app, filename=f"batch{index}.pdf", file_path=str(pdf_path))
            )

        resp = client.post(
            "/api/papers/batch-delete",
            json={"ids": [ids[0], ids[1]]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"deleted": 2, "requested": 2}
        assert not (upload_dir / "batch0.pdf").exists()
        assert not (upload_dir / "batch1.pdf").exists()
        assert (upload_dir / "batch2.pdf").exists()
        remaining = client.get("/api/papers").json()
        assert [p["id"] for p in remaining] == [ids[2]]


def test_batch_delete_empty_ids_returns_zero(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post("/api/papers/batch-delete", json={"ids": []})
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0, "requested": 0}


def test_batch_delete_skips_paths_outside_upload_dir(app_settings, tmp_path):
    app = create_app(app_settings)
    with TestClient(app) as client:
        upload_dir = app.state.settings.pdf_upload_dir
        upload_dir.mkdir(parents=True, exist_ok=True)
        good_path = upload_dir / "good.pdf"
        good_path.write_bytes(b"%PDF-1.7 fake")
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(b"%PDF-1.7 fake")
        good_id = _insert_paper(
            app, filename="good.pdf", file_path=str(good_path)
        )
        outside_id = _insert_paper(
            app, filename="outside.pdf", file_path=str(outside)
        )

        resp = client.post(
            "/api/papers/batch-delete",
            json={"ids": [good_id, outside_id]},
        )
    assert resp.json() == {"deleted": 1, "requested": 2}
    assert outside.exists()


def test_batch_delete_ignores_missing_ids(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        upload_dir = app.state.settings.pdf_upload_dir
        upload_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = upload_dir / "only.pdf"
        pdf_path.write_bytes(b"%PDF-1.7 fake")
        only_id = _insert_paper(app, file_path=str(pdf_path))

        resp = client.post(
            "/api/papers/batch-delete",
            json={"ids": [only_id, 9999]},
        )
    assert resp.json() == {"deleted": 1, "requested": 2}


def _paper_item(**overrides) -> dict:
    item = {
        "title": "LoRA: Low-Rank Adaptation",
        "authors": ["Edward Hu"],
        "abstract": "We propose low-rank adaptation.",
        "source": "arxiv",
        "external_id": "2106.09685",
        "year": 2021,
        "citation_count": 2509,
        "url": "https://arxiv.org/abs/2106.09685",
        "pdf_url": "https://arxiv.org/pdf/2106.09685",
    }
    item.update(overrides)
    return item


def test_import_pdf_downloads_and_stores(app_settings, monkeypatch):
    captured: dict[str, str] = {}

    async def fake_download(url: str) -> bytes:
        captured["url"] = url
        return _make_pdf_bytes()

    monkeypatch.setattr(papers_api, "_download_pdf", fake_download)
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()

    with TestClient(app) as client:
        resp = client.post(
            "/api/papers/import-pdf",
            json={"papers": [_paper_item()]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 1
        assert data["failed"] == []
        assert captured["url"] == "https://arxiv.org/pdf/2106.09685"

        papers = client.get("/api/papers").json()
        assert len(papers) == 1
        assert papers[0]["filename"] == "LoRA: Low-Rank Adaptation.pdf"
        files = list(app.state.settings.pdf_upload_dir.glob("*.pdf"))
        assert len(files) == 1
        assert files[0].read_bytes().startswith(b"%PDF")


def test_import_pdf_derives_arxiv_url(app_settings, monkeypatch):
    captured: dict[str, str] = {}

    async def fake_download(url: str) -> bytes:
        captured["url"] = url
        return _make_pdf_bytes()

    monkeypatch.setattr(papers_api, "_download_pdf", fake_download)
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()

    with TestClient(app) as client:
        item = _paper_item(pdf_url="")
        resp = client.post("/api/papers/import-pdf", json={"papers": [item]})
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1
    assert captured["url"] == "https://arxiv.org/pdf/2106.09685"


def test_import_pdf_skips_papers_without_downloadable_link(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        item = _paper_item(source="s2", external_id="abc", pdf_url="", url="https://x.com/abs/abc")
        resp = client.post("/api/papers/import-pdf", json={"papers": [item]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 0
    assert data["failed"][0]["reason"] == "未找到可下载的 PDF 链接"


def test_import_pdf_rejects_non_pdf_content(app_settings, monkeypatch):
    async def fake_download(url: str) -> bytes:
        return b"this is not a pdf"

    monkeypatch.setattr(papers_api, "_download_pdf", fake_download)
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post(
            "/api/papers/import-pdf",
            json={"papers": [_paper_item()]},
        )
    data = resp.json()
    assert data["imported"] == 0
    assert data["failed"][0]["reason"] == "下载内容不是有效的 PDF"


def test_import_pdf_reports_download_failure(app_settings, monkeypatch):
    async def fake_download(url: str) -> bytes:
        raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))

    monkeypatch.setattr(papers_api, "_download_pdf", fake_download)
    app = create_app(app_settings)
    with TestClient(app) as client:
        resp = client.post(
            "/api/papers/import-pdf",
            json={"papers": [_paper_item()]},
        )
    data = resp.json()
    assert data["imported"] == 0
    assert "下载失败" in data["failed"][0]["reason"]


def test_import_pdf_skips_duplicate_title(app_settings, monkeypatch):
    async def fake_download(url: str) -> bytes:
        return _make_pdf_bytes()

    monkeypatch.setattr(papers_api, "_download_pdf", fake_download)
    app = create_app(app_settings)
    app.state.embedding_service = FakeEmbeddingService()

    with TestClient(app) as client:
        first = client.post(
            "/api/papers/import-pdf",
            json={"papers": [_paper_item()]},
        )
        assert first.json()["imported"] == 1
        pdf_id = client.get("/api/papers").json()[0]["id"]
        _wait_pdf_status(client, pdf_id, "ready")
        second = client.post(
            "/api/papers/import-pdf",
            json={"papers": [_paper_item()]},
        )
    data = second.json()
    assert data["imported"] == 0
    assert data["failed"][0]["reason"] == "已在论文库中"
