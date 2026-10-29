from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.main import create_app
from app.observability.opentelemetry import OpenTelemetryTracer
from app.schemas import DocumentRead, QuestionResponse


class HealthyDatabase:
    async def check(self):
        return {"status": "ok", "database": "ok"}


class TracedDocumentService:
    def __init__(self, tracer: OpenTelemetryTracer) -> None:
        self.tracer = tracer
        now = datetime.now(UTC)
        self.document = DocumentRead(
            id=uuid4(),
            original_filename="private-name.md",
            media_type="text/markdown",
            byte_size=10,
            status="ready",
            chunk_count=1,
            created_at=now,
            updated_at=now,
        )

    async def upload(self, _file):
        with self.tracer.start_span("document.upload"):
            return self.document

    async def list_documents(self):
        return [self.document]

    async def get_document(self, _document_id):
        return self.document

    async def delete_document(self, _document_id):
        with self.tracer.start_span("document.delete"):
            return None

    async def ask(self, _document_id, _question):
        with self.tracer.start_span("document.question"):
            return QuestionResponse(answer="private answer", insufficient_evidence=True, sources=[])


@pytest.mark.asyncio
async def test_http_lifecycle_spans_are_safe_roots_for_business_spans() -> None:
    exporter = InMemorySpanExporter()
    tracer = OpenTelemetryTracer(
        service_name="http-test",
        tracer_name="http-test",
        exporter=exporter,
        batch=False,
    )
    service = TracedDocumentService(tracer)
    app = create_app(
        document_service=service,
        health_checker=HealthyDatabase(),
        observability=tracer,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        upload = await client.post(
            "/api/v1/documents",
            files={"file": ("private-name.md", b"# private", "text/markdown")},
        )
        question = await client.post(
            f"/api/v1/documents/{service.document.id}/questions",
            json={"question": "private question"},
        )
        deletion = await client.delete(f"/api/v1/documents/{service.document.id}")

    assert (upload.status_code, question.status_code, deletion.status_code) == (201, 200, 204)
    spans = {span.name: span for span in exporter.get_finished_spans()}
    pairs = {
        "document.upload": "http.document.upload",
        "document.question": "http.document.question",
        "document.delete": "http.document.delete",
    }
    for child_name, parent_name in pairs.items():
        child = spans[child_name]
        parent = spans[parent_name]
        assert child.parent is not None
        assert child.parent.span_id == parent.context.span_id
        assert parent.attributes["http.response.status_code"] < 400

    exported = repr(exporter.get_finished_spans())
    assert "private question" not in exported
    assert "private answer" not in exported
    assert "private-name.md" not in exported
    tracer.shutdown()
