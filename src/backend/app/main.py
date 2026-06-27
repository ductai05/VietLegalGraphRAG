from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from routes.documents import router as documents_router
from routes.health import router as health_router
from routes.search import router as search_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="VietLegalGraphRAG API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin, "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(search_router)
    app.include_router(documents_router)
    return app


app = create_app()
