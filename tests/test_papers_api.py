"""论文库管理接口测试：列表、删除与路径越界防护。"""

from __future__ import annotations

from fastapi.testclient import TestClient

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

    import asyncio

    return asyncio.run(_insert())


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


def test_import_papers_dedupes_and_lists(app_settings):
    app = create_app(app_settings)
    paper = {
        "title": "LoRA: Low-Rank Adaptation",
        "authors": ["Edward Hu"],
        "abstract": "We propose low-rank adaptation.",
        "source": "arxiv",
        "external_id": "2106.09685",
        "year": 2021,
        "citation_count": 2509,
        "url": "https://arxiv.org/abs/2106.09685",
    }
    with TestClient(app) as client:
        first = client.post("/api/papers/import", json={"papers": [paper]})
        assert first.status_code == 200
        assert first.json() == {"imported": 1, "updated": 0, "skipped": 0}

        again = client.post("/api/papers/import", json={"papers": [paper]})
        assert again.json() == {"imported": 0, "updated": 0, "skipped": 1}

        collection = client.get("/api/papers/collection")
        assert collection.status_code == 200
        assert len(collection.json()) == 1
        assert collection.json()[0]["citation_count"] == 2509


def test_import_updates_citation_count_on_reimport(app_settings):
    app = create_app(app_settings)
    paper = {
        "title": "LoRA",
        "source": "arxiv",
        "external_id": "2106.09685",
        "authors": [],
        "abstract": "",
        "year": 2021,
        "citation_count": 100,
        "url": "",
    }
    newer = {**paper, "citation_count": 2600}
    with TestClient(app) as client:
        client.post("/api/papers/import", json={"papers": [paper]})
        resp = client.post("/api/papers/import", json={"papers": [newer]})
        assert resp.json() == {"imported": 0, "updated": 1, "skipped": 0}
        assert client.get("/api/papers/collection").json()[0]["citation_count"] == 2600


def test_import_stores_and_updates_pdf_url(app_settings):
    app = create_app(app_settings)
    paper = {
        "title": "LoRA",
        "source": "arxiv",
        "external_id": "2106.09685",
        "authors": [],
        "abstract": "",
        "year": 2021,
        "citation_count": 100,
        "url": "https://arxiv.org/abs/2106.09685",
        "pdf_url": "https://arxiv.org/pdf/2106.09685v1",
    }
    with TestClient(app) as client:
        client.post("/api/papers/import", json={"papers": [paper]})
        saved = client.get("/api/papers/collection").json()[0]
        assert saved["pdf_url"] == "https://arxiv.org/pdf/2106.09685v1"

        newer = {
            **paper,
            "citation_count": 101,
            "pdf_url": "https://arxiv.org/pdf/2106.09685v2",
        }
        resp = client.post("/api/papers/import", json={"papers": [newer]})
        assert resp.json() == {"imported": 0, "updated": 1, "skipped": 0}
        assert client.get("/api/papers/collection").json()[0]["pdf_url"] == (
            "https://arxiv.org/pdf/2106.09685v2"
        )


def test_delete_collection_paper(app_settings):
    app = create_app(app_settings)
    paper = {
        "title": "A",
        "source": "s2",
        "external_id": "abc",
        "authors": [],
        "abstract": "",
        "year": 2020,
        "citation_count": 1,
        "url": "",
    }
    with TestClient(app) as client:
        client.post("/api/papers/import", json={"papers": [paper]})
        paper_id = client.get("/api/papers/collection").json()[0]["id"]
        deleted = client.delete(f"/api/papers/collection/{paper_id}")
        assert deleted.status_code == 200
        assert client.get("/api/papers/collection").json() == []
