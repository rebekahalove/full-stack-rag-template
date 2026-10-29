from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentStatus
from app.repositories.documents import DocumentRepository


@pytest.mark.asyncio
async def test_status_update_refreshes_server_managed_timestamp(
    db_session: AsyncSession,
) -> None:
    repository = DocumentRepository(db_session)
    identifier = uuid.uuid4()
    document = await repository.create(
        original_filename="status-refresh.md",
        stored_filename=f"{identifier}.md",
        media_type="text/markdown",
        byte_size=20,
        checksum=identifier.hex,
        status=DocumentStatus.PROCESSING,
    )
    await db_session.commit()

    updated = await repository.update_status(document.id, DocumentStatus.READY)
    await db_session.commit()

    assert updated is not None
    assert updated.status is DocumentStatus.READY
    assert "updated_at" not in inspect(updated).expired_attributes
    assert updated.updated_at is not None

    await repository.delete(document.id)
    await db_session.commit()
