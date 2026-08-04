"""pytest 共享 fixtures。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def app_settings(tmp_path):
    """指向临时目录的应用配置，避免污染真实 data/。"""
    return Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        chroma_persist_dir=tmp_path / "chroma",
        pdf_upload_dir=tmp_path / "uploads",
        app_host="127.0.0.1",
        app_port=0,
    )


@pytest.fixture
def client(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as test_client:
        yield test_client
