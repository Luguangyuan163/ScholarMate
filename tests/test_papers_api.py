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
