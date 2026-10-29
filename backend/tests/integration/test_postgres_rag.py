from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.chunk import Chunk
from app.models.document import DocumentStatus
from app.models.question_event import QuestionEvent
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.rag.generation import StaticAnswerProvider
from app.rag.service import IngestionService, QuestionAnsweringService
from app.repositories.chunks import ChunkRepository
from app.repositories.documents import DocumentRepository


@pytest.mark.asyncio
async def test_migration_enables_pgvector_and_required_indexes(db_session: AsyncSession) -> None:
    extension = await db_session.scalar(
        text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    )
    assert extension == "vector"

    tables = (
        await db_session.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = current_schema() "
                "AND tablename IN ('documents', 'chunks', 'question_events')"
            )
        )
    ).scalars()
    assert set(tables) == {"documents", "chunks", "question_events"}

    vector_type = await db_session.scalar(
        text(
            "SELECT format_type(a.atttypid, a.atttypmod) "
            "FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "WHERE c.relname = 'chunks' AND a.attname = 'embedding'"
        )
    )
    assert vector_type == "vector"

    indexes = (
        await db_session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() AND tablename = 'chunks'"
            )
        )
    ).scalars()
    index_names = set(indexes)
    assert "ix_chunks_embedding_hnsw" not in index_names
    assert "ix_chunks_text_search" in index_names

    check_constraints = (
        await db_session.execute(
            text(
                "SELECT constraint_row.conname "
                "FROM pg_constraint AS constraint_row "
                "JOIN pg_class AS table_row ON table_row.oid = constraint_row.conrelid "
                "WHERE table_row.relname = 'chunks' AND constraint_row.contype = 'c'"
            )
        )
    ).scalars()
    assert "ck_chunks_embedding_dimensions_match" in set(check_constraints)


@pytest.mark.asyncio
async def test_documents_with_different_embedding_dimensions_coexist(
    db_session: AsyncSession,
) -> None:
    repository = DocumentRepository(db_session)
    first = await repository.create(
        original_filename="three.md",
        stored_filename="integration-three-dimensional.md",
        media_type="text/markdown",
        byte_size=10,
        checksum="integration-three-dimensional",
        status=DocumentStatus.READY,
    )
    second = await repository.create(
        original_filename="four.md",
        stored_filename="integration-four-dimensional.md",
        media_type="text/markdown",
        byte_size=10,
        checksum="integration-four-dimensional",
        status=DocumentStatus.READY,
    )
    db_session.add_all(
        [
            Chunk(
                document_id=first.id,
                chunk_index=0,
                content="first embedding space",
                embedding_content="first embedding space",
                token_count=3,
                heading_path=[],
                content_type="text",
                chunk_metadata={},
                embedding=[1.0, 0.0, 0.0],
                embedding_dimensions=3,
            ),
            Chunk(
                document_id=second.id,
                chunk_index=0,
                content="second embedding space",
                embedding_content="second embedding space",
                token_count=3,
                heading_path=[],
                content_type="text",
                chunk_metadata={},
                embedding=[0.0, 1.0, 0.0, 0.0],
                embedding_dimensions=4,
            ),
        ]
    )
    await db_session.commit()

    chunks = ChunkRepository(db_session)
    first_results = await chunks.vector_candidates(
        document_id=first.id,
        query_embedding=[1.0, 0.0, 0.0],
        limit=1,
    )
    second_results = await chunks.vector_candidates(
        document_id=second.id,
        query_embedding=[0.0, 1.0, 0.0, 0.0],
        limit=1,
    )
    wrong_dimension = await chunks.vector_candidates(
        document_id=first.id,
        query_embedding=[1.0, 0.0, 0.0, 0.0],
        limit=1,
    )

    assert [result.chunk.document_id for result in first_results] == [first.id]
    assert [result.chunk.document_id for result in second_results] == [second.id]
    assert wrong_dimension == []

    await repository.delete(first.id)
    await repository.delete(second.id)
    await db_session.commit()


@pytest.mark.asyncio
async def test_ingestion_hybrid_retrieval_question_and_cascade(
    db_session: AsyncSession,
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    repository = DocumentRepository(db_session)
    document = await repository.create(
        original_filename="benefits.md",
        stored_filename="integration-benefits.md",
        media_type="text/markdown",
        byte_size=200,
        checksum="integration-test-checksum",
        status=DocumentStatus.PENDING,
    )
    await db_session.commit()

    source = tmp_path / "benefits.md"
    source.write_text(
        "# Benefits handbook\n\n"
        "## Eligibility\n\n"
        "Coverage begins on the first day of the month following enrollment.\n\n"
        "## Support\n\n"
        "Employees can contact the benefits support team for enrollment questions.\n",
        encoding="utf-8",
    )
    settings = Settings(
        database_url=migrated_database_url,
        openai_api_key=None,
        chunk_min_tokens=1,
        chunk_target_tokens=20,
        chunk_max_tokens=45,
        chunk_overlap_tokens=4,
        embedding_dimensions=3072,
        retrieval_candidates_per_method=10,
        retrieval_final_count=4,
    )
    embeddings = DeterministicEmbeddingProvider(dimensions=3072)
    ingestion = IngestionService(db_session, settings, embedding_provider=embeddings)

    await ingestion.ingest(document.id, source, "text/markdown", source.name)

    await db_session.refresh(document)
    assert document.status == DocumentStatus.READY
    assert document.parser_version
    assert document.document_metadata["chunk_count"] >= 1
    stored_dimensions = await db_session.scalar(
        select(Chunk.embedding_dimensions).where(Chunk.document_id == document.id).limit(1)
    )
    assert stored_dimensions == 3072

    chunks = ChunkRepository(db_session)
    query_vector = (await embeddings.embed(["coverage enrollment begins"]))[0]
    vector_results = await chunks.vector_candidates(
        document_id=document.id,
        query_embedding=query_vector,
        limit=10,
    )
    keyword_results = await chunks.keyword_candidates(
        document_id=document.id,
        query="coverage enrollment",
        limit=10,
    )
    assert vector_results
    assert keyword_results
    assert any("Coverage begins" in result.chunk.content for result in keyword_results)

    answering = QuestionAnsweringService(
        db_session,
        settings,
        embedding_provider=embeddings,
        answer_provider=StaticAnswerProvider(
            answer="Coverage begins on the first day of the month following enrollment."
        ),
    )
    answer = await answering.answer(document.id, "When does coverage begin?")
    assert answer.insufficient_evidence is False
    assert answer.sources
    assert answer.sources[0].document_name == "benefits.md"
    assert "Eligibility" in answer.sources[0].heading_path
    assert (
        await db_session.scalar(
            select(func.count(QuestionEvent.id)).where(QuestionEvent.document_id == document.id)
        )
        == 1
    )

    deleted = await repository.delete(document.id)
    assert deleted is True
    await db_session.commit()
    assert (
        await db_session.scalar(
            select(func.count(Chunk.id)).where(Chunk.document_id == document.id)
        )
        == 0
    )
