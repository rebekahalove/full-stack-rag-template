from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from fastapi import UploadFile

from app.schemas import DocumentRead, QuestionResponse


class DocumentRepositoryProtocol(Protocol):
    async def create(
        self,
        *,
        original_filename: str,
        stored_filename: str,
        media_type: str,
        byte_size: int,
        checksum: str,
        status: str,
    ) -> Any: ...

    async def list(self) -> Sequence[Any]: ...

    async def get(self, document_id: UUID) -> Any | None: ...

    async def delete(self, document_id: UUID) -> bool: ...

    async def update_status(
        self, document_id: UUID, status: str, error_message: str | None = None
    ) -> Any | None: ...

    async def count_chunks(self, document_id: UUID) -> int: ...


class IngestionProtocol(Protocol):
    async def ingest(
        self,
        document_id: UUID,
        path: Path,
        media_type: str,
        original_filename: str,
    ) -> Any: ...


class QuestionAnsweringProtocol(Protocol):
    async def answer(self, document_id: UUID, question: str) -> Any: ...


class DocumentServiceProtocol(Protocol):
    async def upload(self, file: UploadFile) -> DocumentRead: ...

    async def list_documents(self) -> list[DocumentRead]: ...

    async def get_document(self, document_id: UUID) -> DocumentRead: ...

    async def delete_document(self, document_id: UUID) -> None: ...

    async def ask(self, document_id: UUID, question: str) -> QuestionResponse: ...


class HealthCheckerProtocol(Protocol):
    async def check(self) -> dict[str, str]: ...
