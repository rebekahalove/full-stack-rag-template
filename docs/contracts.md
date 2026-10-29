# Shared implementation contract

This document is the stable boundary for parallel implementation. Agents must not edit it.

## API

- `GET /health`
- `POST /api/v1/documents` using multipart field `file`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}`
- `DELETE /api/v1/documents/{document_id}` returning HTTP 204
- `POST /api/v1/documents/{document_id}/questions` with `{ "question": "..." }`

Document JSON fields: `id`, `original_filename`, `media_type`, `byte_size`, `status`,
`chunk_count`, `error_message`, `created_at`, and `updated_at`.

Question response fields: `answer`, `insufficient_evidence`, and `sources`. Each source has
`chunk_id`, `document_id`, `document_name`, `excerpt`, `heading_path`, `page_start`, `page_end`,
and `score`.

## Backend service boundaries

The API layer calls a document service. The document service may call ingestion and question
answering services exposed by `app.rag`. Tests may replace both with deterministic fakes. OpenAI
network calls must never occur at import time.

The RAG package exposes an ingestion operation accepting a document ID, local path, media type,
and original filename, plus a question operation accepting a document ID and question. Concrete
types can remain internal as long as the API contract is honored.

## Persistence

Use UUID primary keys. `documents` owns many `chunks` with delete cascade. Chunks retain original
content, enriched embedding content, token count, heading path, page range, offsets, content type,
metadata JSONB, a text-search vector, and a provider-configurable embedding with its validated
dimension. Enable the `vector` extension and add the text-search index. A fixed-space production
deployment may add a dimension-specific vector index.

## Errors

- Invalid or unsupported uploads: HTTP 422.
- Uploads over configured size: HTTP 413.
- Missing documents: HTTP 404.
- Questions for documents that are not ready: HTTP 409.
- Provider or unexpected processing failures: persist failed status and return a safe HTTP 500.

## Agent ownership

- API agent: `backend/app/api`, `backend/app/schemas`, `backend/app/services`, `backend/app/main.py`,
  and `backend/tests/unit/api`.
- RAG/database agent: `backend/app/db`, `backend/app/models`, `backend/app/repositories`,
  `backend/app/rag`, `backend/migrations`, and `backend/tests/unit/rag`.
- Frontend agent: all files below `frontend`.
- Integration/docs agent: `backend/tests/integration`, `tests/e2e`, and all files below `docs`
  except this contract.
- Coordinator: root-level files, `backend/pyproject.toml`, and `backend/app/core`.
