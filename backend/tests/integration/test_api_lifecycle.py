from __future__ import annotations

from pathlib import Path
from uuid import UUID

import httpx
import pytest

from .conftest import minimal_docx_bytes, minimal_pdf_bytes


@pytest.mark.asyncio
async def test_health_and_document_question_lifecycle(
    api_client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    health = await api_client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "database": "ok"}

    upload = await api_client.post(
        "/api/v1/documents",
        files={
            "file": (
                "benefits.md",
                b"# Benefits\n\nCoverage begins after enrollment.",
                "text/markdown",
            )
        },
    )
    assert upload.status_code == 201
    uploaded = upload.json()
    document_id = uploaded["id"]
    assert uploaded["original_filename"] == "benefits.md"
    assert uploaded["media_type"] == "text/markdown"
    assert uploaded["status"] == "ready"
    assert uploaded["chunk_count"] == 2
    assert uploaded["error_message"] is None
    assert len(list((tmp_path / "uploads").glob("*.md"))) == 1

    listing = await api_client.get("/api/v1/documents")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [document_id]

    detail = await api_client.get(f"/api/v1/documents/{document_id}")
    assert detail.status_code == 200
    assert detail.json()["original_filename"] == "benefits.md"

    answer = await api_client.post(
        f"/api/v1/documents/{document_id}/questions",
        json={"question": "  When does coverage begin?  "},
    )
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["insufficient_evidence"] is False
    assert "first day" in payload["answer"]
    assert payload["sources"][0]["document_id"] == document_id
    assert payload["sources"][0]["heading_path"] == ["Benefits handbook", "Eligibility"]

    insufficient = await api_client.post(
        f"/api/v1/documents/{document_id}/questions",
        json={"question": "What is the dental deductible?"},
    )
    assert insufficient.status_code == 200
    assert insufficient.json()["insufficient_evidence"] is True
    assert insufficient.json()["sources"] == []

    deleted = await api_client.delete(f"/api/v1/documents/{document_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert not list((tmp_path / "uploads").iterdir())

    missing = await api_client.get(f"/api/v1/documents/{document_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "expected_media_type"),
    [
        ("guide.md", b"# Guide\n\nA useful paragraph.", "text/markdown"),
        ("guide.pdf", minimal_pdf_bytes(), "application/pdf"),
        (
            "guide.docx",
            minimal_docx_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
async def test_supported_upload_formats_reach_ingestion(
    api_client: httpx.AsyncClient,
    ingestion,
    filename: str,
    content: bytes,
    expected_media_type: str,
) -> None:
    response = await api_client.post(
        "/api/v1/documents",
        files={"file": (filename, content, "application/octet-stream")},
    )
    assert response.status_code == 201
    assert response.json()["media_type"] == expected_media_type
    _, saved_path, media_type, original_filename = ingestion.calls[-1]
    assert saved_path.exists()
    assert media_type == expected_media_type
    assert original_filename == filename


@pytest.mark.asyncio
async def test_invalid_uploads_and_requests_return_contract_errors(
    api_client: httpx.AsyncClient,
    repository,
) -> None:
    unsupported = await api_client.post(
        "/api/v1/documents",
        files={"file": ("notes.txt", b"not supported", "text/plain")},
    )
    assert unsupported.status_code == 422

    malformed_pdf = await api_client.post(
        "/api/v1/documents",
        files={"file": ("notes.pdf", b"not a pdf", "application/pdf")},
    )
    assert malformed_pdf.status_code == 422

    oversized = await api_client.post(
        "/api/v1/documents",
        files={"file": ("large.md", b"x" * (110 * 1024), "text/markdown")},
    )
    assert oversized.status_code == 413

    missing_id = "e28f9688-70da-487d-8a96-d6a8a5c7d561"
    missing = await api_client.get(f"/api/v1/documents/{missing_id}")
    assert missing.status_code == 404

    blank_question = await api_client.post(
        f"/api/v1/documents/{missing_id}/questions",
        json={"question": "   "},
    )
    assert blank_question.status_code == 422

    upload = await api_client.post(
        "/api/v1/documents",
        files={"file": ("processing.md", b"# Processing", "text/markdown")},
    )
    document_id = upload.json()["id"]
    repository.documents[UUID(document_id)].status = "processing"
    not_ready = await api_client.post(
        f"/api/v1/documents/{document_id}/questions",
        json={"question": "What does this say?"},
    )
    assert not_ready.status_code == 409
