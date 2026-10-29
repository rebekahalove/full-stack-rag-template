from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.question_event import QuestionEvent


def _document(identifier: uuid.UUID, label: str) -> Document:
    return Document(
        id=identifier,
        original_filename=f"{label}.md",
        stored_filename=f"{identifier}.md",
        media_type="text/markdown",
        checksum=identifier.hex,
        byte_size=100,
        status=DocumentStatus.READY,
        document_metadata={},
    )


def _chunk(document_id: uuid.UUID, identifier: uuid.UUID) -> Chunk:
    return Chunk(
        id=identifier,
        document_id=document_id,
        chunk_index=0,
        content="Coverage begins after enrollment.",
        embedding_content="Coverage begins after enrollment.",
        token_count=5,
        heading_path=["Eligibility"],
        content_type="text",
        chunk_metadata={},
        embedding=[0.0] * 1536,
        embedding_dimensions=1536,
    )


def _question_event(document_id: uuid.UUID, identifier: uuid.UUID) -> QuestionEvent:
    return QuestionEvent(
        id=identifier,
        document_id=document_id,
        question="When does coverage begin?",
        answer="After enrollment.",
        retrieved_chunk_ids=[],
        event_metadata={},
    )


@pytest.mark.asyncio
async def test_raw_document_delete_cascades_only_to_owned_rows(
    db_session: AsyncSession,
) -> None:
    target_id = uuid.uuid4()
    retained_id = uuid.uuid4()
    target_chunk_id = uuid.uuid4()
    retained_chunk_id = uuid.uuid4()
    target_event_id = uuid.uuid4()
    retained_event_id = uuid.uuid4()
    db_session.add_all(
        [
            _document(target_id, "target"),
            _document(retained_id, "retained"),
            _chunk(target_id, target_chunk_id),
            _chunk(retained_id, retained_chunk_id),
            _question_event(target_id, target_event_id),
            _question_event(retained_id, retained_event_id),
        ]
    )
    await db_session.commit()

    foreign_keys = (
        await db_session.execute(
            text(
                "SELECT child.relname AS child_table, "
                "CASE constraint_row.confdeltype "
                "WHEN 'c' THEN 'CASCADE' "
                "ELSE constraint_row.confdeltype::text "
                "END AS delete_action "
                "FROM pg_constraint AS constraint_row "
                "JOIN pg_class AS child ON child.oid = constraint_row.conrelid "
                "WHERE constraint_row.contype = 'f' "
                "AND constraint_row.confrelid = 'documents'::regclass"
            )
        )
    ).all()
    assert {row.child_table: row.delete_action for row in foreign_keys} == {
        "chunks": "CASCADE",
        "question_events": "CASCADE",
    }

    await db_session.execute(
        text("DELETE FROM documents WHERE id = :document_id"),
        {"document_id": target_id},
    )
    await db_session.commit()

    assert (
        await db_session.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == target_id))
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count(QuestionEvent.id)).where(QuestionEvent.document_id == target_id)
        )
        == 0
    )
    assert (
        await db_session.scalar(select(func.count(Document.id)).where(Document.id == target_id))
        == 0
    )

    assert (
        await db_session.scalar(select(func.count(Document.id)).where(Document.id == retained_id))
        == 1
    )
    assert (
        await db_session.scalar(select(func.count(Chunk.id)).where(Chunk.id == retained_chunk_id))
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count(QuestionEvent.id)).where(QuestionEvent.id == retained_event_id)
        )
        == 1
    )

    await db_session.execute(
        text("DELETE FROM documents WHERE id = :document_id"),
        {"document_id": retained_id},
    )
    await db_session.commit()
