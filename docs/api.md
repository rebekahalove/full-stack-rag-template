# HTTP API

The API uses JSON except for document upload. Identifiers are UUID strings and timestamps are
ISO 8601 values. The examples below omit headers that are not relevant to the contract.

## Health

### `GET /health`

Returns application health and, when implemented, database readiness. A successful response uses
HTTP 200. Clients should not rely on fields beyond a top-level health/status indicator unless they
are added to the shared contract.

## Documents

### `POST /api/v1/documents`

Upload exactly one PDF, DOCX, or Markdown document as multipart field `file`.

```bash
curl -F "file=@handbook.pdf" http://localhost:8000/api/v1/documents
```

On success, the response contains the document representation:

```json
{
  "id": "66d51b8b-dbc0-43c8-88aa-3bf662e85d6c",
  "original_filename": "handbook.pdf",
  "media_type": "application/pdf",
  "byte_size": 42871,
  "status": "ready",
  "chunk_count": 12,
  "error_message": null,
  "created_at": "2026-10-27T14:30:00Z",
  "updated_at": "2026-10-27T14:30:01Z"
}
```

Because MVP ingestion is synchronous, a successful response is ready to query. Invalid,
unsupported, empty, or malformed content returns HTTP 422; content above the configured limit
returns HTTP 413. An unexpected parsing, persistence, or provider failure returns a safe HTTP 500
and records the failed state when possible.

### `GET /api/v1/documents`

Returns uploaded documents. The MVP does not promise pagination or ordering; consumers should not
infer either unless the response contract is extended.

### `GET /api/v1/documents/{document_id}`

Returns one document representation. An unknown ID returns HTTP 404.

### `DELETE /api/v1/documents/{document_id}`

Deletes the database record, chunks, embeddings, and stored source. Success returns HTTP 204 with
no body. An unknown ID returns HTTP 404. Repeating a successful deletion therefore returns 404.

## Questions

### `POST /api/v1/documents/{document_id}/questions`

```json
{
  "question": "When does coverage begin?"
}
```

The question must be non-empty. A successful response is:

```json
{
  "answer": "Coverage begins on the first day of the month after enrollment.",
  "insufficient_evidence": false,
  "sources": [
    {
      "chunk_id": "13e211b7-ea1e-431e-89ea-9709adb1ea47",
      "document_id": "66d51b8b-dbc0-43c8-88aa-3bf662e85d6c",
      "document_name": "handbook.pdf",
      "excerpt": "Coverage begins on the first day of the month following enrollment.",
      "heading_path": ["Benefits", "Effective date"],
      "page_start": 7,
      "page_end": 7,
      "score": 0.91
    }
  ]
}
```

When retrieved evidence does not support an answer, the endpoint still returns HTTP 200 with
`insufficient_evidence: true`, an explanatory answer, and zero or more low-confidence sources.
Unknown documents return HTTP 404; documents that are not ready return HTTP 409.

## Error shape

FastAPI validation errors conventionally return a `detail` field. Callers should use the HTTP
status as the stable error category and treat explanatory text as human-readable rather than a
machine-stable code.

| Condition | Status |
| --- | ---: |
| Invalid or unsupported upload/request | 422 |
| Upload exceeds configured maximum | 413 |
| Document does not exist | 404 |
| Document is not ready for questions | 409 |
| Unexpected processing/provider failure | 500 |

## Browser access

Development CORS allows the configured frontend origin, normally `http://localhost:5173`. Add
explicit trusted origins for other environments; do not use a wildcard when credentials or user
data are introduced.
