"""应用配置：基于 pydantic-settings，读取 .env 与环境变量。"""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用形态
    app_host: str = "127.0.0.1"
    app_port: int = 8765
    app_title: str = "ScholarMate"
    app_size: str = "1280x800"

    # LLM 主模型
    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    dashscope_api_key: str = ""
    dashscope_model: str = "qwen-plus"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Embedding
    embedding_provider: str = "dashscope"
    embedding_model: str = "text-embedding-v3"

    # 外部 API
    semantic_scholar_api_key: str = ""
    openalex_mailto: str = ""

    # 存储
    database_url: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'data' / 'scholar_mate.db').as_posix()}"
    chroma_persist_dir: Path = BASE_DIR / "data" / "chroma_db"
    pdf_upload_dir: Path = BASE_DIR / "data" / "uploads"
    max_upload_mb: int = 50

    @field_validator("chroma_persist_dir", "pdf_upload_dir")
    @classmethod
    def _resolve_relative_path(cls, value: Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else BASE_DIR / path

    def ensure_dirs(self) -> None:
        """创建运行时数据目录（首次启动 / 打包后首次运行）。"""
        self.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_upload_dir.mkdir(parents=True, exist_ok=True)
