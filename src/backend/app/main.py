from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from routes.documents import router as documents_router
from routes.health import router as health_router
from routes.search import router as search_router


def _cors_origins(frontend_origin: str) -> list[str]:
    origins = {
        origin.strip()
        for origin in frontend_origin.split(",")
        if origin.strip()
    }
    origins.update({"http://localhost:5173", "http://127.0.0.1:5173"})
    return sorted(origins)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="VietLegalGraphRAG API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings.frontend_origin),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(search_router)
    app.include_router(documents_router)
    _register_error_handlers(app)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    """Structured error responses; never leak raw tracebacks to clients.

    - ValueError is reserved for request/config validation -> 422.
    - Any other unhandled exception is treated as an expected dependency or
      configuration failure (Elasticsearch, Neo4j, reranker, LLM) -> 502 with
      a generic, non-sensitive message.
    """

    @app.exception_handler(ValueError)
    async def _handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "error": "dependency_error",
                "detail": (
                    "Upstream service or configuration failure. "
                    "Check /health for service status."
                ),
            },
        )


app = create_app()
