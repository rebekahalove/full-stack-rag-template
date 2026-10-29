from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from app.observability.interface import Span, TraceAttribute


class NoOpSpan:
    def set_attribute(self, key: str, value: TraceAttribute) -> None:
        return None

    def add_event(
        self,
        name: str,
        attributes: Mapping[str, TraceAttribute] | None = None,
    ) -> None:
        return None

    def record_exception(self, exception: BaseException) -> None:
        return None

    def set_error(self, description: str = "operation failed") -> None:
        return None


class NoOpTracer:
    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: Mapping[str, TraceAttribute] | None = None,
    ) -> Iterator[Span]:
        yield NoOpSpan()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True

    def shutdown(self) -> None:
        return None
