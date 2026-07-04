from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from routes.documents import router as documents_router
from routes.health import router as health_router
from routes.search import router as search_router

# Ensure the services package is importable (it lives next to the app dir)
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "services"))

from vm_manager import VMManager  # noqa: E402

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown.

    On startup:  create and start the VM watchdog.
    On shutdown: cancel the watchdog gracefully.
    """
    settings = get_settings()

    vm = VMManager(
        provider=settings.vm_provider,
        idle_timeout=settings.vm_idle_timeout,
    )
    app.state.vm_manager = vm
    await vm.start_watchdog()
    logger.info(
        "VMManager initialised (provider=%s, idle_timeout=%ds)",
        settings.vm_provider,
        settings.vm_idle_timeout,
    )

    yield  # Application runs here

    # Shutdown
    await vm.shutdown()
    logger.info("VMManager shut down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="VietLegalGraphRAG API",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def activity_tracker(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Reset the VM idle timer on every incoming request."""
        vm_manager = getattr(request.app.state, "vm_manager", None)
        if vm_manager is not None:
            vm_manager.touch()
        response: Response = await call_next(request)
        return response

    app.include_router(health_router)
    app.include_router(search_router)
    app.include_router(documents_router)
    return app


app = create_app()
