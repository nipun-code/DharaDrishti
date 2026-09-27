"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq.connections import ArqRedis
from fastapi import FastAPI

from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from app.db.redis import create_redis
from app.db.session import create_engine, create_session_factory
from app.services.ingestion.embedder import SentenceTransformerEmbedder
from app.services.retrieval.reranker import CrossEncoderReranker

logger = logging.getLogger(__name__)

# Allowance for multipart boundaries and form fields on top of the file-size limit.
_FORM_OVERHEAD = 1024 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings)
        app.state.session_factory = create_session_factory(app.state.engine)
        app.state.redis = create_redis(settings)
        # Job queue client (bytes-mode Redis, as ARQ requires). Connects lazily on first use.
        app.state.arq = ArqRedis.from_url(settings.redis_url)
        # Models load lazily on first use (run `python -m app.cli download-models` to pre-fetch).
        app.state.embedder = SentenceTransformerEmbedder(
            settings.embedding_model_name,
            batch_size=settings.embedding_batch_size,
            device=settings.embedding_device,
            query_instruction=settings.embedding_query_instruction,
        )
        app.state.reranker = CrossEncoderReranker(
            settings.reranker_model_name,
            device=settings.embedding_device,
            max_length=settings.reranker_max_length,
            batch_size=settings.reranker_batch_size,
        )
        logger.info("app_startup", extra={"environment": settings.environment})
        try:
            yield
        finally:
            await app.state.arq.aclose()
            await app.state.redis.aclose()
            await app.state.engine.dispose()
            logger.info("app_shutdown")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )
    app.state.settings = settings

    # Last added = outermost: request ids are assigned before the size check can reject.
    app.add_middleware(
        BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes + _FORM_OVERHEAD
    )
    app.add_middleware(RequestContextMiddleware, header_name=settings.request_id_header)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router, prefix="/api/v1")
    return app
