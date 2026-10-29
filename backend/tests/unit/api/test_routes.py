from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.schemas import DocumentRead, QuestionResponse, SourceRead
from app.services.errors import DocumentNotFoundError


def make_document(*, status: str = "ready") -> DocumentRead:
    now = datetime.now(UTC)
    return DocumentRead(
        id=uuid4(),
        original_filename="benefits.md",
        media_type="text/markdown",
        byte_size=42,
        status=status,
        chunk_count=2,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


class FakeDocumentService:
    def __init__(self) -> None:
        self.document = make_document()
        self.question: str | None = None
        self.deleted: UUID | None = None

    async def upload(self, file):
        assert file.filename == "benefits.md"
        assert await file.read() == b"# Benefits"
        return self.document

    async def list_documents(self):
        return [self.document]

    async def get_document(self, document_id):
        if document_id != self.document.id:
            raise DocumentNotFoundError()
        return self.document

    async def delete_document(self, document_id):
        await self.get_document(document_id)
        self.deleted = document_id

    async def ask(self, document_id, question):
        await self.get_document(document_id)
        self.question = question
        return QuestionResponse(
            answer="Coverage begins on the first day.",
            insufficient_evidence=False,
            sources=[
                SourceRead(
                    chunk_id=uuid4(),
                    document_id=document_id,
                    document_name="benefits.md",
                    excerpt="Coverage begins on the first day.",
                    heading_path=["Eligibility"],
                    page_start=None,
                    page_end=None,
                    score=0.91,
                )
            ],
        )


class FakeHealthChecker:
    async def check(self):
        return {"status": "ok", "database": "ok"}


@pytest.fixture
def service():
    return FakeDocumentService()


@pytest.fixture
async def client(service):
    app = create_app(document_service=service, health_checker=FakeHealthChecker())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_health_and_document_lifecycle_routes(client, service):
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "database": "ok"}

    upload = await client.post(
        "/api/v1/documents",
        files={"file": ("benefits.md", b"# Benefits", "text/markdown")},
    )
    assert upload.status_code == 201
    assert upload.json()["id"] == str(service.document.id)

    listing = await client.get("/api/v1/documents")
    assert listing.status_code == 200
    assert listing.json()[0]["original_filename"] == "benefits.md"

    detail = await client.get(f"/api/v1/documents/{service.document.id}")
    assert detail.status_code == 200
    assert detail.json()["chunk_count"] == 2

    deletion = await client.delete(f"/api/v1/documents/{service.document.id}")
    assert deletion.status_code == 204
    assert deletion.content == b""
    assert service.deleted == service.document.id


@pytest.mark.asyncio
async def test_question_is_trimmed_and_sources_are_returned(client, service):
    response = await client.post(
        f"/api/v1/documents/{service.document.id}/questions",
        json={"question": "  When does coverage begin?  "},
    )

    assert response.status_code == 200
    assert service.question == "When does coverage begin?"
    body = response.json()
    assert body["insufficient_evidence"] is False
    assert body["sources"][0]["heading_path"] == ["Eligibility"]


@pytest.mark.asyncio
async def test_question_rejects_blank_input(client, service):
    response = await client.post(
        f"/api/v1/documents/{service.document.id}/questions",
        json={"question": "   "},
    )

    assert response.status_code == 422
    assert service.question is None


@pytest.mark.asyncio
async def test_service_errors_use_safe_http_shape(client):
    response = await client.get(f"/api/v1/documents/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found."}
