from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from threading import Lock
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Status, StatusCode

from app.observability.interface import Span, TraceAttribute

_FORBIDDEN_ATTRIBUTE_PARTS = frozenset(
    {
        "answer",
        "api_key",
        "authorization",
        "content",
        "document_text",
        "filename",
        "file_path",
        "password",
        "prompt",
        "question",
        "secret",
        "token_value",
    }
)


def _safe_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(".", "_")
    return not any(part in normalized for part in _FORBIDDEN_ATTRIBUTE_PARTS)


def _safe_attributes(
    attributes: Mapping[str, TraceAttribute] | None,
) -> dict[str, TraceAttribute]:
    if not attributes:
        return {}
    return {key: value for key, value in attributes.items() if _safe_key(key)}


class OpenTelemetrySpan:
    def __init__(self, span: trace.Span) -> None:
        self._span = span

    def set_attribute(self, key: str, value: TraceAttribute) -> None:
        if _safe_key(key):
            self._span.set_attribute(key, value)

    def add_event(
        self,
        name: str,
        attributes: Mapping[str, TraceAttribute] | None = None,
    ) -> None:
        self._span.add_event(name, _safe_attributes(attributes))

    def record_exception(self, exception: BaseException) -> None:
        """Record failure type without exception text, stack, arguments, or local values."""
        exception_type = type(exception).__name__
        self._span.set_attribute("error.type", exception_type)
        self._span.add_event(
            "exception",
            {
                "exception.type": exception_type,
                "exception.escaped": True,
            },
        )
        self.set_error()

    def set_error(self, description: str = "operation failed") -> None:
        del description
        self._span.set_status(Status(StatusCode.ERROR, "operation failed"))


class OpenTelemetryTracer:
    """OpenTelemetry SDK adapter without global-provider side effects."""

    def __init__(
        self,
        *,
        service_name: str,
        tracer_name: str,
        exporter: SpanExporter,
        batch: bool,
    ) -> None:
        resource = Resource.create({SERVICE_NAME: service_name})
        self._provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(exporter) if batch else SimpleSpanProcessor(exporter)
        self._provider.add_span_processor(processor)
        self._tracer = self._provider.get_tracer(tracer_name)
        self._shutdown_lock = Lock()
        self._shutdown = False

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: Mapping[str, TraceAttribute] | None = None,
    ) -> Iterator[Span]:
        with self._tracer.start_as_current_span(
            name,
            attributes=_safe_attributes(attributes),
            record_exception=False,
            set_status_on_exception=False,
        ) as sdk_span:
            span = OpenTelemetrySpan(sdk_span)
            try:
                yield span
            except BaseException as exc:
                span.record_exception(exc)
                raise

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._provider.force_flush(timeout_millis)

    def shutdown(self) -> None:
        with self._shutdown_lock:
            if self._shutdown:
                return
            self._shutdown = True
        self._provider.shutdown()


def create_otlp_tracer(
    *, service_name: str, tracer_name: str, endpoint: str, batch: bool
) -> OpenTelemetryTracer:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    exporter: Any = OTLPSpanExporter(endpoint=endpoint)
    return OpenTelemetryTracer(
        service_name=service_name,
        tracer_name=tracer_name,
        exporter=exporter,
        batch=batch,
    )
