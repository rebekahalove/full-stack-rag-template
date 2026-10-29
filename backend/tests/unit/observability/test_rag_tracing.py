from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.config import Settings
from app.models.document import DocumentStatus
from app.observability.opentelemetry import OpenTelemetryTracer
from app.rag.generation.providers import StaticAnswerProvider
from app.rag.provider_factory import embedding_space_for_provider
from app.rag.service import IngestionService, QuestionAnsweringService, RAGConfigurationError
from app.rag.types import ChunkDraft, ExtractedBlock, ExtractedDocument, RetrievedChunk


def make_tracer() -> tuple[OpenTelemetryTracer, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    tracer = OpenTelemetryTracer(
        service_name="rag-test",
        tracer_name="rag-test",
        exporter=exporter,
        batch=False,
    )
    return tracer, exporter


class FakeSession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeDocuments:
    def __init__(self, document) -> None:
        self.document = document

    async def get(self, document_id):
        return self.document if self.document.id == document_id else None

    async def update_status(self, document_id, status, **_values):
        assert document_id == self.document.id
        self.document.status = DocumentStatus(status)
        return self.document


class FakeChunks:
    def __init__(self) -> None:
        self.values = []

    async def replace_for_document(self, _document_id, values) -> None:
        self.values = values


class FakeEmbeddingProvider:
    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions

    async def embed(self, texts):
        return [[0.0] * self.dimensions for _ in texts]


class FakeChunker:
    def chunk(self, _extracted):
        return [
            ChunkDraft(
                chunk_index=0,
                content="private document body",
                embedding_content="private document body",
                token_count=3,
                heading_path=["Private heading"],
                page_start=1,
                page_end=1,
                offset_start=0,
                offset_end=21,
                content_type="paragraph",
            )
        ]


class FakeRetriever:
    def __init__(self, result) -> None:
        self.result = result

    async def retrieve(self, **_kwargs):
        return [self.result]


class FakeEvents:
    async def create(self, **_values) -> None:
        return None


def assert_children(spans, parent_name: str, child_names: set[str]) -> None:
    parent = spans[parent_name]
    for child_name in child_names:
        child = spans[child_name]
        assert child.parent is not None
        assert child.parent.span_id == parent.context.span_id


@pytest.mark.asyncio
async def test_ingestion_stage_spans_are_children_and_contain_only_safe_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tracer, exporter = make_tracer()
    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        status=DocumentStatus.PENDING,
        document_metadata={},
    )
    extracted = ExtractedDocument(
        title="private title",
        source_path=tmp_path / "private-name.md",
        blocks=[ExtractedBlock(content="private document body")],
    )
    monkeypatch.setattr("app.rag.service.extract_document", lambda *_args: extracted)
    service = IngestionService(
        FakeSession(),
        Settings(embedding_dimensions=3072),
        embedding_provider=FakeEmbeddingProvider(dimensions=3072),
        chunker=FakeChunker(),
        tracer=tracer,
    )
    service.documents = FakeDocuments(document)
    service.chunks = FakeChunks()

    with tracer.start_span("http.document.upload"):
        await service.ingest(document_id, tmp_path / "private-name.md", "text/markdown", "x.md")

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["rag.ingest"].parent.span_id == spans["http.document.upload"].context.span_id
    assert_children(
        spans,
        "rag.ingest",
        {
            "rag.extract",
            "rag.chunk",
            "rag.embedding.batch",
            "db.chunks.replace",
        },
    )
    assert spans["rag.extract"].attributes["rag.extracted_block_count"] == 1
    assert spans["rag.chunk"].attributes["rag.chunk_count"] == 1
    assert spans["rag.embedding.batch"].attributes["rag.batch_size"] == 1
    assert service.chunks.values[0].embedding_dimensions == 3072
    assert service.chunks.values[0].chunk_metadata["embedding_dimensions"] == 3072
    exported = repr(exporter.get_finished_spans())
    assert "private document body" not in exported
    assert "private title" not in exported
    assert "private-name.md" not in exported
    tracer.shutdown()


@pytest.mark.asyncio
async def test_question_traces_embedding_retrieval_generation_and_persistence() -> None:
    tracer, exporter = make_tracer()
    document_id = uuid4()
    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        chunk_index=0,
        content="private retrieved passage",
        heading_path=["Private heading"],
        page_start=1,
        page_end=1,
        score=0.9,
    )
    document = SimpleNamespace(
        id=document_id,
        status=DocumentStatus.READY,
        original_filename="private-name.md",
        document_metadata={
            "embedding_space": embedding_space_for_provider(FakeEmbeddingProvider(dimensions=3072))
        },
    )
    service = QuestionAnsweringService(
        FakeSession(),
        Settings(embedding_dimensions=3072),
        embedding_provider=FakeEmbeddingProvider(dimensions=3072),
        answer_provider=StaticAnswerProvider(answer="private generated answer"),
        retriever=FakeRetriever(chunk),
        tracer=tracer,
    )
    service.documents = FakeDocuments(document)
    service.events = FakeEvents()

    with tracer.start_span("http.document.question"):
        result = await service.answer(document_id, "private user question")

    assert result.insufficient_evidence is False
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["rag.question"].parent.span_id == spans["http.document.question"].context.span_id
    assert_children(
        spans,
        "rag.question",
        {
            "rag.embedding.query",
            "rag.retrieve",
            "rag.generate",
            "db.question_event.create",
        },
    )
    assert spans["rag.retrieve"].attributes["rag.result_count"] == 1
    assert spans["rag.generate"].attributes["rag.context_count"] == 1
    exported = repr(exporter.get_finished_spans())
    assert "private user question" not in exported
    assert "private generated answer" not in exported
    assert "private retrieved passage" not in exported
    assert "private-name.md" not in exported
    tracer.shutdown()


@pytest.mark.asyncio
async def test_question_rejects_a_different_embedding_dimension_before_retrieval() -> None:
    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        status=DocumentStatus.READY,
        original_filename="document.md",
        document_metadata={
            "embedding_space": embedding_space_for_provider(FakeEmbeddingProvider(dimensions=3072))
        },
    )
    service = QuestionAnsweringService(
        FakeSession(),
        Settings(embedding_dimensions=1536),
        embedding_provider=FakeEmbeddingProvider(dimensions=1536),
        retriever=FakeRetriever(None),
    )
    service.documents = FakeDocuments(document)

    with pytest.raises(RAGConfigurationError, match="do not match"):
        await service.answer(document_id, "question")
