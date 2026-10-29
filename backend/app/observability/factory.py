from app.core.config import Settings
from app.observability.interface import Tracer
from app.observability.noop import NoOpTracer


def create_observability(settings: Settings) -> Tracer:
    if not settings.observability_enabled:
        return NoOpTracer()

    from app.observability.opentelemetry import create_otlp_tracer

    return create_otlp_tracer(
        service_name=settings.otel_service_name,
        tracer_name=settings.otel_tracer_name,
        endpoint=settings.otel_exporter_otlp_endpoint,
        batch=settings.otel_batch_export,
    )
