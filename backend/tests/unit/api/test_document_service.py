from datetime import UTC, datetime
from pathlib import Path
from tempfile import SpooledTemporaryFile
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import UploadFile

from app.services.documents import DocumentService
from app.services.errors import (
    DocumentNotReadyError,
    InvalidUploadError,
    ProcessingError,
    UploadTooLargeError,
)


class FakeRepository:
    def __init__(self) -> None:
        self.records = {}
        self.status_updates = []

    async def create(self, **values):
        now = datetime.now(UTC)
        record = SimpleNamespace(
            id=uuid4(), error_message=None, created_at=now, updated_at=now, **values
        )
        self.records[record.id] = record
        return record

    async def list(self):
        return list(self.records.values())

    async def get(self, document_id):
        return self.records.get(document_id)

    async def delete(self, document_id):
        return self.records.pop(document_id, None) is not None

    async def update_status(self, document_id, status, error_message=None):
        record = self.records.get(document_id)
        if record is not None:
            record.status = status
            record.error_message = error_message
            record.updated_at = datetime.now(UTC)
            self.status_updates.append((document_id, status, error_message))
        return record

    async def count_chunks(self, _document_id):
        return 3


class FakeIngestion:
    def __init__(self, *, error=None) -> None:
        self.call = None
        self.error = error

    async def ingest(self, document_id, path, media_type, original_filename):
        self.call = (document_id, path, media_type, original_filename)
        if self.error:
            raise self.error


class FakeQuestionAnswering:
    async def answer(self, document_id, question):
        return {
            "answer": f"Answer to {question}",
            "insufficient_evidence": True,
            "sources": [],
        }


def make_service(tmp_path: Path, *, ingestion=None, max_mb=1):
    repository = FakeRepository()
    ingestion = ingestion or FakeIngestion()
    service = DocumentService(
        repository,
        ingestion,
        FakeQuestionAnswering(),
        upload_directory=tmp_path,
        max_upload_size_mb=max_mb,
        upload_read_size_bytes=1024,
        upload_pdf_header_bytes=1024,
        allowed_extensions=[".pdf", ".docx", ".md"],
        question_max_characters=4000,
    )
    return service, repository, ingestion


def make_upload(filename: str, content: bytes) -> UploadFile:
    source = SpooledTemporaryFile(max_size=1024 * 1024)
    source.write(content)
    source.seek(0)
    return UploadFile(filename=filename, file=source)


@pytest.mark.asyncio
async def test_upload_stores_ingests_and_returns_ready_document(tmp_path):
    service, repository, ingestion = make_service(tmp_path)
    upload = make_upload("guide.md", b"# Guide\nUseful text")

    result = await service.upload(upload)

    assert result.status == "ready"
    assert result.chunk_count == 3
    assert result.media_type == "text/markdown"
    assert ingestion.call[0] == result.id
    stored_path = ingestion.call[1]
    assert stored_path.read_text() == "# Guide\nUseful text"
    assert repository.status_updates[-1][1] == "ready"


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_empty_and_oversized_files(tmp_path):
    service, _, _ = make_service(tmp_path, max_mb=0)

    with pytest.raises(InvalidUploadError):
        await service.upload(make_upload("notes.txt", b"content"))
    with pytest.raises(UploadTooLargeError):
        await service.upload(make_upload("notes.md", b"content"))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_ingestion_failure_marks_document_failed(tmp_path):
    ingestion = FakeIngestion(error=RuntimeError("provider secret must not leak"))
    service, repository, _ = make_service(tmp_path, ingestion=ingestion)

    with pytest.raises(ProcessingError, match="Document processing failed"):
        await service.upload(make_upload("guide.md", b"# Guide"))

    record = next(iter(repository.records.values()))
    assert record.status == "failed"
    assert record.error_message == "Document processing failed."


@pytest.mark.asyncio
async def test_question_requires_ready_document(tmp_path):
    service, repository, _ = make_service(tmp_path)
    document = await repository.create(
        original_filename="guide.md",
        stored_filename="stored.md",
        media_type="text/markdown",
        byte_size=1,
        checksum="abc",
        status="processing",
    )

    with pytest.raises(DocumentNotReadyError):
        await service.ask(document.id, "What is covered?")
