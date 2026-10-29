# Configuration

This repository is designed to be copied as a general-purpose document RAG template. Runtime
choices live in the root `.env.example`, grouped by the module that owns them. Application code
does not provide a second set of deployable defaults.

## Precedence

The backend loads `.env.example` first and `.env` second. The example file is therefore the
version-controlled baseline, while `.env` contains machine-specific overrides and secrets. Vite
uses the same root directory for its `VITE_*` values.

For a new project:

```bash
cp .env.example .env
```

Then change the database credentials, application identity, provider key, and any RAG tuning
values in `.env`. Never put a real provider key or database password in `.env.example`.

## Module ownership

| Group | Owning code | What belongs there |
| --- | --- | --- |
| Application / API | `backend/app/main.py` | API identity and CORS policy |
| Database | `backend/app/db` | URLs and SQLAlchemy connection/session behavior |
| Development launcher | `scripts/dev.sh` | service hosts/ports and optional shared-infrastructure paths |
| Uploads | `backend/app/services/documents.py` | storage path, size, streaming, signatures, allowed formats |
| Parsing | `backend/app/rag/extraction` | parser version and format-specific heuristics |
| Chunking | `backend/app/rag/chunking` | tokenizer fallback, target/min/max sizes, overlap |
| Providers | `backend/app/rag/providers` | credentials, provider endpoints, native API options |
| Embeddings | `backend/app/rag/providers` | provider, model, vector dimensions, task modes, batch size |
| Retrieval | `backend/app/rag/retrieval` | candidate counts, RRF constant, deduplication threshold |
| Answer generation | `backend/app/rag/providers` | provider, model, grounding instructions, evidence behavior, limits |
| Evaluation | `backend/app/evaluation` | paid-run trial/question limits and wall-time timeout |
| Frontend | `frontend/src` | branding, API URL, mirrored browser-side validation limits |
| Observability | `backend/app/observability` | enablement, OTLP destination, service/tracer identity, batching |

## Values that must stay aligned

- `EMBEDDING_DIMENSIONS` must match the selected provider/model output and may be changed without a
  schema migration. Existing documents still belong to their original embedding space and must be
  re-uploaded or re-embedded before they can be queried with the new configuration. The generic
  schema accepts pgvector `vector` values up to 16,000 dimensions.
- `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, and the query/document task modes together identify an
  embedding space. Existing documents must be re-uploaded after any of these change; the backend
  rejects a query when its current embedding space does not match the stored document metadata.
- `EMBEDDING_API_KEY` and `EMBEDDING_BASE_URL` are optional generic overrides. When blank, the
  selected provider's named key and endpoint are used. Chat has equivalent `CHAT_*` overrides.
- `VITE_MAX_UPLOAD_SIZE_MB` and `VITE_ALLOWED_UPLOAD_EXTENSIONS` provide early browser feedback;
  the backend `MAX_UPLOAD_SIZE_MB` and `UPLOAD_ALLOWED_EXTENSIONS` remain authoritative.
- `VITE_QUESTION_MAX_CHARACTERS` should match `QUESTION_MAX_CHARACTERS`.
- `PARSER_VERSION` should be incremented when parsing behavior changes in a way that matters to
  already-indexed documents.
- `DEV_BACKEND_PORT`, `DEV_BACKEND_HEALTH_URL`, `VITE_API_BASE_URL`, and the configured CORS origin
  must describe the same local API/frontend topology when ports are customized. Equivalent
  `DEV_FRONTEND_*` values control the launcher readiness check.
- `SHARED_POSTGRES_*` and `SHARED_JAEGER_*` identify reusable local infrastructure. Relative
  compose paths are resolved from the repository root; they are not application deployment
  settings.

Model values are intentionally free-form strings rather than a hard-coded enum. Provider catalogs
change often, while saved evaluation trials need to pin the exact identifier used for a result.
See [provider selection](providers.md) for capability and configuration details.

## What remains in code

Protocol and schema invariants remain in code: HTTP status codes, supported MIME mappings, PDF and
DOCX signatures, database column sizes, pgvector's maximum supported dimensions, route paths, and
test-only fixture values. These are implementation contracts rather than deployable defaults. If
an invariant needs to become configurable, update its validation and storage schema at the same
time.
