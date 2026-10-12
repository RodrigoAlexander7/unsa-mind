"""Fábrica de la aplicación FastAPI (REST + A2A)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from unsa_mind.config.container import Container, bootstrap, build_container
from unsa_mind.config.settings import Settings, get_settings
from unsa_mind.interfaces.a2a.router import router as a2a_router
from unsa_mind.interfaces.a2a.service import A2AService
from unsa_mind.interfaces.api import admin, chat, health
from unsa_mind.interfaces.api.deps import RateLimiter

log = logging.getLogger(__name__)


def _wire(app: FastAPI, container: Container) -> None:
    app.state.container = container
    app.state.a2a = A2AService(container.ask, container.settings)


def create_app(
    container: Container | None = None,
    *,
    settings: Settings | None = None,
    rate_limit_per_minute: int = 20,
) -> FastAPI:
    """Crea la app. Sin `container`, lo construye en el arranque con `build_container`."""
    cfg = container.settings if container else (settings or get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = container or build_container(cfg)
        _wire(app, c)
        await bootstrap(c)
        started = False
        if c.settings.run_scheduler:
            schedule = await c.settings_repo.get_schedule()

            async def job() -> None:
                await c.update_cycle.execute()

            c.scheduler.start(job, schedule)
            started = True
            log.info("Scheduler iniciado (%s)", schedule)
        try:
            yield
        finally:
            if started:
                c.scheduler.shutdown()

    app = FastAPI(
        title="Asistente Virtual UNSA",
        version="0.1.0",
        description="API REST + protocolo A2A del asistente institucional de la UNSA.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.rate_limiter = RateLimiter(rate_limit_per_minute) if rate_limit_per_minute > 0 else None
    if container is not None:
        _wire(app, container)

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(admin.router)
    app.include_router(a2a_router)
    return app
