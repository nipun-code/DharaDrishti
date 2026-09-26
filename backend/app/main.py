"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.redis import create_redis
from app.db.session import create_engine, create_session_factory

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings)
        app.state.session_factory = create_session_factory(app.state.engine)
        app.state.redis = create_redis(settings)
        logger.info("app_startup", extra={"environment": settings.environment})
        try:
            yield
        finally:
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

    app.add_middleware(RequestContextMiddleware, header_name=settings.request_id_header)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router, prefix="/api/v1")
    return app
