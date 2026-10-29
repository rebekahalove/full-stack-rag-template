from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol

type TraceScalar = str | bool | int | float
type TraceAttribute = TraceScalar | Sequence[TraceScalar]


class Span(Protocol):
    """Application-facing span with deliberately small, vendor-neutral capabilities."""

    def set_attribute(self, key: str, value: TraceAttribute) -> None: ...

    def add_event(
        self,
        name: str,
        attributes: Mapping[str, TraceAttribute] | None = None,
    ) -> None: ...

    def record_exception(self, exception: BaseException) -> None: ...

    def set_error(self, description: str = "operation failed") -> None: ...


class Tracer(Protocol):
    """Tracing interface used by business code, independent of an observability vendor."""

    def start_span(
        self,
        name: str,
        attributes: Mapping[str, TraceAttribute] | None = None,
    ) -> AbstractContextManager[Span]: ...

    def force_flush(self, timeout_millis: int = 30_000) -> bool: ...

    def shutdown(self) -> None: ...
