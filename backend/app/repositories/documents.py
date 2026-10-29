import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        original_filename: str,
        stored_filename: str,
        media_type: str,
        byte_size: int,
        checksum: str,
        status: DocumentStatus | str = DocumentStatus.PENDING,
    ) -> Document:
        document = Document(
            original_filename=original_filename,
            stored_filename=stored_filename,
            media_type=media_type,
            byte_size=byte_size,
            checksum=checksum,
            status=DocumentStatus(status),
        )
        self.session.add(document)
        await self.session.flush()
        return document

    async def list(self) -> list[Document]:
        result = await self.session.scalars(select(Document).order_by(Document.created_at.desc()))
        return list(result)

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return await self.session.get(Document, document_id)

    async def delete(self, document_id: uuid.UUID) -> bool:
        document = await self.get(document_id)
        if document is None:
            return False
        await self.session.delete(document)
        await self.session.flush()
        return True

    async def update_status(
        self,
        document_id: uuid.UUID,
        status: DocumentStatus | str,
        error_message: str | None = None,
        *,
        parser_version: str | None = None,
    ) -> Document | None:
        document = await self.get(document_id)
        if document is None:
            return None
        document.status = DocumentStatus(status)
        document.error_message = error_message
        if parser_version is not None:
            document.parser_version = parser_version
        await self.session.flush()
        # ``updated_at`` is produced by the database during UPDATE. SQLAlchemy
        # expires that attribute after the flush; refresh it while we are still
        # inside an awaited ORM operation so later response serialization cannot
        # trigger an implicit async load (and therefore MissingGreenlet).
        await self.session.refresh(document, attribute_names=["updated_at"])
        return document

    async def count_chunks(self, document_id: uuid.UUID) -> int:
        statement = select(func.count(Chunk.id)).where(Chunk.document_id == document_id)
        return int((await self.session.scalar(statement)) or 0)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
