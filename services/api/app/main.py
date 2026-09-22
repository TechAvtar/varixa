"""FastAPI application factory."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.database import create_engine, create_session_factory
from app.providers.storage import build_storage
from app.utils.request_id import RequestIdMiddleware
from app.workers.retention import run_periodically


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Runs on server startup (not on import), so tooling/tests that import
        # the module never create local directories or DB connections as a side effect.
        settings.ensure_local_dirs()
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.storage = build_storage(settings)
        sweeper: asyncio.Task[None] | None = None
        if settings.retention_sweep_interval_minutes > 0 and settings.environment != "test":
            sweeper = asyncio.create_task(
                run_periodically(app.state.session_factory, app.state.storage, settings)
            )
        try:
            yield
        finally:
            if sweeper is not None:
                sweeper.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sweeper
            await engine.dispose()

    app = FastAPI(
        lifespan=lifespan,
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )

    # Middleware order: the last added runs first, so the request id exists
    # before CORS and before any handler.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.add_middleware(RequestIdMiddleware)

    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    # Make the settings object used to build the app the one routes receive,
    # so tests can inject configuration without touching process env.
    app.dependency_overrides[get_settings] = lambda: settings
    return app


app = create_app()
