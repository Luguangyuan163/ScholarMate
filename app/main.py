"""FastAPI 应用工厂：组装配置、数据库、路由、模板与静态资源。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

import app.models  # noqa: F401  确保 ORM 模型注册到 Base.metadata
from app.api import agent, conversations, papers, pdf, search, translations
from app.config import Settings
from app.core.database import Database
from app.core.llm_client import get_llm_client
from app.models.uploaded_pdf import UploadedPDF
from app.services.arxiv_service import ArxivService
from app.services.embedding_service import EmbeddingService
from app.services.metadata_service import FallbackMetadataSource
from app.services.openalex_service import OpenAlexService
from app.services.pdf_service import PDFService
from app.services.semantic_scholar_service import SemanticScholarService
from app.services.translation_service import TranslationService
from app.services.vector_store_service import VectorStoreService

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_dirs()
        await db.create_all()
        app.state.database = db
        app.state.settings = settings
        app.state.templates = templates
        if not hasattr(app.state, "arxiv_service"):
            app.state.arxiv_service = ArxivService()
        if not hasattr(app.state, "s2_service"):
            app.state.s2_service = SemanticScholarService(
                api_key=settings.semantic_scholar_api_key
            )
        if not hasattr(app.state, "openalex_service"):
            app.state.openalex_service = OpenAlexService(mailto=settings.openalex_mailto)
        if not hasattr(app.state, "metadata_service"):
            app.state.metadata_service = FallbackMetadataSource(
                s2=app.state.s2_service,
                openalex=app.state.openalex_service,
                prefer_s2=bool(settings.semantic_scholar_api_key),
            )
        if not hasattr(app.state, "pdf_service"):
            app.state.pdf_service = PDFService()
        if not hasattr(app.state, "embedding_service"):
            app.state.embedding_service = EmbeddingService(
                api_key=settings.dashscope_api_key, model=settings.embedding_model
            )
        if not hasattr(app.state, "vector_store"):
            app.state.vector_store = VectorStoreService(
                persist_dir=settings.chroma_persist_dir
            )
        if not hasattr(app.state, "processing_progress"):
            app.state.processing_progress = {}
        async with db.session_factory() as session:
            stale = (
                await session.execute(
                    select(UploadedPDF).where(UploadedPDF.status == "processing")
                )
            ).scalars().all()
            for row in stale:
                row.status = "failed"
            if stale:
                await session.commit()
        if not hasattr(app.state, "llm_client"):
            app.state.llm_client = get_llm_client(settings)
        if not hasattr(app.state, "translation_service"):
            app.state.translation_service = TranslationService(
                llm=app.state.llm_client
            )
        yield
        await db.close()

    app = FastAPI(title=settings.app_title, version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_title}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "chat.html", {"app_title": settings.app_title})

    @app.get("/agent", response_class=HTMLResponse)
    async def agent_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "chat.html", {"app_title": settings.app_title})

    @app.get("/search", response_class=HTMLResponse)
    async def search_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", {"app_title": settings.app_title})

    @app.get("/translate", response_class=HTMLResponse)
    async def translate_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "chat.html", {"app_title": settings.app_title})

    @app.get("/papers", response_class=HTMLResponse)
    async def papers_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "papers.html", {"app_title": settings.app_title})

    app.include_router(search.router)
    app.include_router(agent.router)
    app.include_router(conversations.router)
    app.include_router(pdf.router)
    app.include_router(papers.router)
    app.include_router(translations.router)
    return app
