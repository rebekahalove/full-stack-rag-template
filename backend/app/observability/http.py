import re
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from app.observability.interface import Tracer

_DOCUMENT_ROUTE = re.compile(r"^/api/v1/documents/[^/]+$")
_QUESTION_ROUTE = re.compile(r"^/api/v1/documents/[^/]+/questions$")


def _operation(method: str, path: str) -> tuple[str, str]:
    if method == "POST" and path == "/api/v1/documents":
        return "http.document.upload", "/api/v1/documents"
    if method == "POST" and _QUESTION_ROUTE.fullmatch(path):
        return "http.document.question", "/api/v1/documents/{document_id}/questions"
    if method == "DELETE" and _DOCUMENT_ROUTE.fullmatch(path):
        return "http.document.delete", "/api/v1/documents/{document_id}"
    if method == "GET" and _DOCUMENT_ROUTE.fullmatch(path):
        return "http.document.get", "/api/v1/documents/{document_id}"
    if method == "GET" and path == "/api/v1/documents":
        return "http.document.list", "/api/v1/documents"
    if method == "GET" and path == "/health":
        return "http.health", "/health"
    return "http.request", "unmatched"


async def trace_http_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    tracer: Tracer,
) -> Response:
    operation, route = _operation(request.method, request.url.path)
    with tracer.start_span(
        operation,
        {
            "http.request.method": request.method,
            "http.route": route,
        },
    ) as span:
        response = await call_next(request)
        span.set_attribute("http.response.status_code", response.status_code)
        if response.status_code >= 500:
            span.set_error("server error")
        return response
