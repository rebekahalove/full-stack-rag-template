from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.observability.interface import Tracer
from app.services.documents import DocumentService
from app.services.health import DatabaseHealthChecker
from app.services.protocols import DocumentServiceProtocol, HealthCheckerProtocol


async def get_database_session() -> AsyncIterator[Any]:
    """Yield a session while keeping database imports lazy and test-friendly."""
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        yield session


DatabaseSession = Annotated[Any, Depends(get_database_session)]


async def get_settings_dependency() -> Settings:
    """Expose cached settings without dispatching a synchronous dependency to a thread."""
    return get_settings()


SettingsDependency = Annotated[Settings, Depends(get_settings_dependency)]


async def get_observability(request: Request) -> Tracer:
    return request.app.state.observability


ObservabilityDependency = Annotated[Tracer, Depends(get_observability)]


async def get_document_service(
    session: DatabaseSession,
    settings: SettingsDependency,
    observability: ObservabilityDependency,
) -> DocumentServiceProtocol:
    """Compose production adapters for one request.

    Tests and alternate deployments can override this dependency without importing
    or contacting an external model provider.
    """
    from app.rag import IngestionService, QuestionAnsweringService
    from app.repositories.documents import DocumentRepository

    repository = DocumentRepository(session)
    ingestion = IngestionService(session, settings, tracer=observability)
    question_answering = QuestionAnsweringService(session, settings, tracer=observability)
    return DocumentService(
        repository,
        ingestion,
        question_answering,
        upload_directory=settings.upload_directory,
        max_upload_size_mb=settings.max_upload_size_mb,
        upload_read_size_bytes=settings.upload_read_size_bytes,
        upload_pdf_header_bytes=settings.upload_pdf_header_bytes,
        allowed_extensions=settings.upload_allowed_extensions,
        question_max_characters=settings.question_max_characters,
        tracer=observability,
    )


async def get_health_checker(
    session: DatabaseSession,
) -> HealthCheckerProtocol:
    return DatabaseHealthChecker(session)
