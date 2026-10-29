import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.core.config import Settings
from app.observability.factory import create_observability
from app.observability.noop import NoOpTracer
from app.observability.opentelemetry import OpenTelemetryTracer


def make_tracer() -> tuple[OpenTelemetryTracer, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    tracer = OpenTelemetryTracer(
        service_name="observability-test",
        tracer_name="observability-test",
        exporter=exporter,
        batch=False,
    )
    return tracer, exporter


def test_disabled_configuration_uses_noop_and_enabled_requires_endpoint() -> None:
    assert isinstance(create_observability(Settings(observability_enabled=False)), NoOpTracer)
    with pytest.raises(ValueError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        Settings(observability_enabled=True, otel_exporter_otlp_endpoint="")


def test_spans_preserve_hierarchy_and_filter_sensitive_attributes() -> None:
    tracer, exporter = make_tracer()
    with tracer.start_span(
        "http.document.upload",
        {
            "http.request.method": "POST",
            "document.filename": "private-benefits.pdf",
            "question": "private question",
        },
    ):
        with tracer.start_span(
            "rag.embedding.batch",
            {"rag.batch_size": 3, "document.content": "private document text"},
        ):
            pass

    spans = {span.name: span for span in exporter.get_finished_spans()}
    parent = spans["http.document.upload"]
    child = spans["rag.embedding.batch"]
    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id
    assert child.attributes["rag.batch_size"] == 3
    assert parent.attributes["http.request.method"] == "POST"
    all_attributes = {key for span in spans.values() for key in span.attributes}
    assert "document.filename" not in all_attributes
    assert "document.content" not in all_attributes
    assert "question" not in all_attributes

    tracer.shutdown()
    tracer.shutdown()


def test_failure_records_only_safe_exception_type_and_error_status() -> None:
    tracer, exporter = make_tracer()
    secret = "never-export-this-question-or-key"

    try:
        with tracer.start_span("rag.generate"):
            raise ValueError(secret)
    except ValueError:
        pass

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "operation failed"
    assert span.attributes["error.type"] == "ValueError"
    assert len(span.events) == 1
    assert span.events[0].name == "exception"
    assert span.events[0].attributes["exception.type"] == "ValueError"
    exported = repr((span.attributes, span.events, span.status))
    assert secret not in exported
    assert "exception.message" not in exported
    assert "exception.stacktrace" not in exported
    tracer.shutdown()
