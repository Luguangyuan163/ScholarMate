"""配置模块测试：默认值与环境变量覆盖。"""

from __future__ import annotations

from app.config import Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 8765
    assert settings.deepseek_model == "deepseek-v4-flash"
    assert settings.embedding_provider == "dashscope"
    assert settings.max_upload_mb == 50


def test_env_override(monkeypatch):
    monkeypatch.setenv("APP_PORT", "9000")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("MAX_UPLOAD_MB", "20")
    settings = Settings(_env_file=None)
    assert settings.app_port == 9000
    assert settings.deepseek_model == "deepseek-v4-pro"
    assert settings.max_upload_mb == 20
