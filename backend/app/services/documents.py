import hashlib
import logging
import os
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import UploadFile

from app.observability import NoOpTracer, Span, Tracer
from app.schemas import DocumentRead, QuestionResponse
from app.services.errors import (
    DocumentNotFoundError,
    DocumentNotReadyError,
    InvalidQuestionError,
    InvalidUploadError,
    ProcessingError,
    UploadTooLargeError,
)
from app.services.protocols import (
    DocumentRepositoryProtocol,
    IngestionProtocol,
    QuestionAnsweringProtocol,
)

logger = logging.getLogger(__name__)

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
}


class DocumentService:
    """Coordinates safe local storage, persistence, ingestion, and Q&A."""

    def __init__(
        self,
        repository: DocumentRepositoryProtocol,
        ingestion: IngestionProtocol,
        question_answering: QuestionAnsweringProtocol,
        *,
        upload_directory: Path,
        max_upload_size_mb: float,
        upload_read_size_bytes: int,
        upload_pdf_header_bytes: int,
        allowed_extensions: Sequence[str],
        question_max_characters: int,
        tracer: Tracer | None = None,
    ) -> None:
        self._repository = repository
        self._ingestion = ingestion
        self._question_answering = question_answering
        self._upload_directory = upload_directory
        self._max_upload_bytes = int(max_upload_size_mb * 1024 * 1024)
        self._upload_read_size_bytes = upload_read_size_bytes
        self._upload_pdf_header_bytes = upload_pdf_header_bytes
        self._allowed_extensions = frozenset(allowed_extensions)
        unsupported = self._allowed_extensions.difference(_MEDIA_TYPES)
        if unsupported:
            raise ValueError(f"Unsupported configured upload extensions: {sorted(unsupported)}")
        self._question_max_characters = question_max_characters
        self._tracer = tracer or NoOpTracer()

    async def upload(self, file: UploadFile) -> DocumentRead:
        with self._tracer.start_span("document.upload") as span:
            document = await self._upload(file, span)
            span.set_attribute("document.id", str(document.id))
            span.set_attribute("document.media_type", document.media_type)
            span.set_attribute("document.byte_size", document.byte_size)
            span.set_attribute("document.chunk_count", document.chunk_count)
            span.set_attribute("document.status", document.status)
            return document

    async def _upload(self, file: UploadFile, span: Span) -> DocumentRead:
        original_filename, extension, media_type = self._validate_filename(file.filename)
        span.set_attribute("document.media_type", media_type)
        self._upload_directory.mkdir(parents=True, exist_ok=True)

        stored_filename = f"{uuid4()}{extension}"
        final_path = self._upload_directory / stored_filename
        temporary_path = final_path.with_suffix(f"{extension}.uploading")

        byte_size = 0
        digest = hashlib.sha256()
        try:
            with temporary_path.open("xb") as target:
                while content := await file.read(self._upload_read_size_bytes):
                    byte_size += len(content)
                    if byte_size > self._max_upload_bytes:
                        limit_mb = self._max_upload_bytes / (1024 * 1024)
                        raise UploadTooLargeError(f"Upload exceeds the {limit_mb:g} MB limit.")
                    digest.update(content)
                    target.write(content)

            if byte_size == 0:
                raise InvalidUploadError("Uploaded documents cannot be empty.")
            self._validate_file_content(temporary_path, extension)
            os.replace(temporary_path, final_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise

        document: Any | None = None
        try:
            with self._tracer.start_span("db.document.create") as persistence_span:
                document = await self._repository.create(
                    original_filename=original_filename,
                    stored_filename=stored_filename,
                    media_type=media_type,
                    byte_size=byte_size,
                    checksum=digest.hexdigest(),
                    status="processing",
                )
                persistence_span.set_attribute("document.id", str(document.id))
            await self._ingestion.ingest(
                document.id,
                final_path,
                media_type,
                original_filename,
            )
            with self._tracer.start_span(
                "db.document.status",
                {"document.id": str(document.id), "document.status": "ready"},
            ):
                updated = await self._repository.update_status(document.id, "ready", None)
                await self._commit_repository()
            document = updated or await self._repository.get(document.id) or document
            return await self._serialize_document(document)
        except Exception as exc:
            if document is None:
                final_path.unlink(missing_ok=True)
            else:
                try:
                    with self._tracer.start_span(
                        "db.document.status",
                        {"document.id": str(document.id), "document.status": "failed"},
                    ):
                        await self._repository.update_status(
                            document.id, "failed", "Document processing failed."
                        )
                        await self._commit_repository()
                except Exception:
                    logger.exception("Could not persist failed status for document %s", document.id)
            logger.exception("Document ingestion failed for %s", original_filename)
            raise ProcessingError() from exc

    async def list_documents(self) -> list[DocumentRead]:
        records = await self._repository.list()
        return [await self._serialize_document(record) for record in records]

    async def get_document(self, document_id: UUID) -> DocumentRead:
        document = await self._require_document(document_id)
        return await self._serialize_document(document)

    async def delete_document(self, document_id: UUID) -> None:
        with self._tracer.start_span("document.delete", {"document.id": str(document_id)}):
            document = await self._require_document(document_id)
            stored_filename = _get_value(document, "stored_filename")
            with self._tracer.start_span("db.document.delete", {"document.id": str(document_id)}):
                deleted = await self._repository.delete(document_id)
                if not deleted:
                    raise DocumentNotFoundError()
                await self._commit_repository()
            if stored_filename:
                (self._upload_directory / str(stored_filename)).unlink(missing_ok=True)

    async def ask(self, document_id: UUID, question: str) -> QuestionResponse:
        if len(question) > self._question_max_characters:
            raise InvalidQuestionError(
                f"Question exceeds the {self._question_max_characters} character limit."
            )
        with self._tracer.start_span(
            "document.question", {"document.id": str(document_id)}
        ) as span:
            document = await self._require_document(document_id)
            status = getattr(
                _get_value(document, "status"), "value", _get_value(document, "status")
            )
            if status != "ready":
                raise DocumentNotReadyError()
            try:
                result = await self._question_answering.answer(document_id, question)
                response = QuestionResponse.model_validate(result)
                span.set_attribute("rag.insufficient_evidence", response.insufficient_evidence)
                span.set_attribute("rag.source_count", len(response.sources))
                return response
            except (DocumentNotFoundError, DocumentNotReadyError):
                raise
            except Exception as exc:
                logger.exception("Question answering failed for document %s", document_id)
                raise ProcessingError("Question answering failed.") from exc

    async def _require_document(self, document_id: UUID) -> Any:
        document = await self._repository.get(document_id)
        if document is None:
            raise DocumentNotFoundError()
        return document

    async def _serialize_document(self, document: Any) -> DocumentRead:
        values = _as_dict(document)
        if values.get("chunk_count") is None:
            values["chunk_count"] = await self._repository.count_chunks(values["id"])
        return DocumentRead.model_validate(values)

    async def _commit_repository(self) -> None:
        """Commit when the concrete repository exposes a transaction boundary.

        In-memory adapters intentionally need not implement this optional hook.
        SQLAlchemy repositories expose their session, allowing the application
        service to make deletes and terminal status changes durable.
        """
        commit = getattr(self._repository, "commit", None)
        if commit is not None:
            await commit()
            return
        session = getattr(self._repository, "session", None)
        if session is not None:
            await session.commit()

    def _validate_filename(self, filename: str | None) -> tuple[str, str, str]:
        if not filename:
            raise InvalidUploadError("A filename is required.")
        normalized = PurePosixPath(filename.replace("\\", "/")).name
        if normalized in {"", ".", ".."}:
            raise InvalidUploadError("A valid filename is required.")
        extension = Path(normalized).suffix.lower()
        media_type = _MEDIA_TYPES.get(extension)
        if media_type is None or extension not in self._allowed_extensions:
            allowed = ", ".join(sorted(self._allowed_extensions))
            raise InvalidUploadError(f"Unsupported file type. Allowed extensions: {allowed}.")
        return normalized, extension, media_type

    def _validate_file_content(self, path: Path, extension: str) -> None:
        if extension == ".pdf":
            with path.open("rb") as source:
                header = source.read(self._upload_pdf_header_bytes)
            if not header.lstrip().startswith(b"%PDF-"):
                raise InvalidUploadError("The uploaded file is not a valid PDF.")
        elif extension == ".docx":
            try:
                with ZipFile(path) as archive:
                    names = set(archive.namelist())
                    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                        raise InvalidUploadError("The uploaded file is not a valid DOCX document.")
            except BadZipFile as exc:
                raise InvalidUploadError("The uploaded file is not a valid DOCX document.") from exc
        elif extension == ".md":
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise InvalidUploadError("Markdown documents must use UTF-8 encoding.") from exc
            if not content.strip():
                raise InvalidUploadError("Uploaded documents cannot be empty.")


def _get_value(record: Any, key: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(key)
    return getattr(record, key, None)


def _as_dict(record: Any) -> dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    fields: Sequence[str] = (
        "id",
        "original_filename",
        "media_type",
        "byte_size",
        "status",
        "chunk_count",
        "error_message",
        "created_at",
        "updated_at",
    )
    return {field: getattr(record, field, None) for field in fields}
