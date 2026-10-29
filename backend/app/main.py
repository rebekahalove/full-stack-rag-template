import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import (
    get_document_service,
    get_health_checker,
    get_settings_dependency,
)
from app.api.routes import documents_router, health_router
from app.core.config import Settings, get_settings
from app.observability import Tracer, create_observability
from app.observability.http import trace_http_request
from app.services.errors import ServiceError
from app.services.protocols import DocumentServiceProtocol, HealthCheckerProtocol

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    document_service: DocumentServiceProtocol | None = None,
    health_checker: HealthCheckerProtocol | None = None,
    observability: Tracer | None = None,
    lifespan: Callable[[FastAPI], AsyncIterator[None]] | None = None,
) -> FastAPI:
    """Create the application with explicit seams for deterministic tests."""
    app_settings = settings or get_settings()
    app_observability = observability or create_observability(app_settings)
    custom_lifespan = lifespan

    @asynccontextmanager
    async def managed_lifespan(app: FastAPI) -> AsyncIterator[None]:
        app_settings.upload_directory.mkdir(parents=True, exist_ok=True)
        try:
            if custom_lifespan is None:
                yield
            else:
                async with custom_lifespan(app):
                    yield
        finally:
            app_observability.shutdown()

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description=app_settings.app_description,
        lifespan=managed_lifespan,
    )
    app.state.observability = app_observability
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.backend_cors_origins,
        allow_credentials=app_settings.backend_cors_allow_credentials,
        allow_methods=app_settings.backend_cors_allow_methods,
        allow_headers=app_settings.backend_cors_allow_headers,
    )
    app.include_router(health_router)
    app.include_router(documents_router)

    @app.middleware("http")
    async def observe_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        return await trace_http_request(request, call_next, app_observability)

    @app.exception_handler(ServiceError)
    async def handle_service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled request error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})

    if settings is not None:

        async def override_settings() -> Settings:
            return app_settings

        app.dependency_overrides[get_settings_dependency] = override_settings
    if document_service is not None:

        async def override_document_service() -> DocumentServiceProtocol:
            return document_service

        app.dependency_overrides[get_document_service] = override_document_service
    if health_checker is not None:

        async def override_health_checker() -> HealthCheckerProtocol:
            return health_checker

        app.dependency_overrides[get_health_checker] = override_health_checker

    return app


app = create_app()
