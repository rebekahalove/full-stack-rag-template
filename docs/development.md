# Development guide

## Prerequisites

- Python 3.12 or newer and `uv`
- Node.js 20 or newer and npm
- The standalone `shared-postgresql` Docker service
- An OpenAI API key for real ingestion and question answering

The automated suites use deterministic fakes and must not spend provider credits.

## First-time setup

From the repository root:

1. Copy `.env.example` to `.env` and set the required values.
2. Replace the placeholder database passwords in `.env`.
3. Start the standalone PostgreSQL service with `make db-up`.
4. Install/synchronize backend dependencies with `cd backend && uv sync --dev`.
5. Apply migrations with `cd backend && uv run alembic upgrade head`.
6. Install frontend dependencies with `cd frontend && npm install`.

The normal development launcher starts shared PostgreSQL and Jaeger when needed, applies pending
Alembic migrations, and starts FastAPI and React in the background:

```bash
make dev-start
make dev-status
```

Runtime PID files and logs are written below `.runtime/`. Use `make dev-restart` to restart both
web services and `make dev-stop` to stop them. The stop command intentionally leaves shared
PostgreSQL and Jaeger running for other projects.

To run the services interactively instead, run FastAPI from `backend`:

```bash
uv run uvicorn app.main:app --reload
```

Run React from `frontend` in another terminal:

```bash
npm run dev
```

The default UI and API are expected at `http://localhost:5173` and `http://localhost:8000`.
Configure alternate development hosts, ports, readiness URLs, container names, or sibling compose
paths in the local `.env` using the `DEV_*` and `SHARED_*` keys documented in `.env.example`.

## Configuration

Configuration is loaded from `.env`; never commit that file. Important categories are:

- database connection;
- OpenAI credential, chat model, and embedding model;
- embedding dimension, which must match the selected embedding model output;
- upload directory and maximum upload size;
- chunk target/minimum/maximum and overlap;
- retrieval candidate and final result counts;
- allowed browser origins.
- optional OpenTelemetry tracing, service name, and OTLP/HTTP trace endpoint.

Chunk limits must satisfy `minimum <= target <= maximum`, with overlap below the target. The
configured embedding dimension must be between 1 and 16,000 and agree with the provider request.
Stored rows record their actual dimension, and queries only compare matching dimensions.

## Shared database dependency

PostgreSQL 16 with pgvector is managed by the standalone sibling project at
`../shared-postgresql`, outside this application repository:

- container: `postgresql-for-all-projects`;
- persistent volume: `postgresql-for-all-projects-data`;
- shared network: `postgresql-for-all-projects-network`;
- reference databases: `rag_template` and `rag_template_test`;
- reference login role: `rag_template`.

These names are deliberately generic defaults. A project created from this template should choose
and provision a unique role and database pair before its first migration. See the
[template customization checklist](template-customization.md).

This application may start an existing shared container and inspect it:

```bash
make db-up
docker ps --filter name=postgresql-for-all-projects
```

Server-wide operations such as creating, recreating, or stopping the shared container belong in
the standalone infrastructure project because they affect every application using it.

Relative `UPLOAD_DIRECTORY` values are resolved from the repository root, so the default
`./storage` location is stable whether the backend is launched directly or through the Makefile.

Other host-run projects can use `localhost:5434`. A containerized project can declare
`postgresql-for-all-projects-network` as an external network and connect to the hostname
`postgresql-for-all-projects`. Give every project its own role and databases rather than sharing
another project's credentials.

Stopping or removing the container does not delete the explicitly named volume. Deleting
`postgresql-for-all-projects-data` destroys every project database in this shared instance and
must be done only after confirming backups.

See [Shared PostgreSQL dependency](shared-postgresql.md) for this application's connection and
provisioning details.

Schema changes are made through Alembic revisions. A fresh database must reach the complete schema
with `alembic upgrade head`; a downgrade is optional unless a revision explicitly supports it.

Document deletion semantics live in PostgreSQL. The `chunks.document_id` and
`question_events.document_id` foreign keys use `ON DELETE CASCADE`, so deleting a document through
the repository or raw SQL atomically deletes both dependent row sets. Unrelated documents and
their children are not affected. Integration coverage should exercise a raw document delete—not
only ORM deletion—and verify both the dependent cleanup and unrelated-row preservation. The
uploaded source file is outside PostgreSQL and is removed separately by the document service.

## OpenTelemetry tracing

Tracing is disabled by default and has no exporter side effects in that mode. Enable the modular
OpenTelemetry adapter with these exact `.env` settings:

```dotenv
OBSERVABILITY_ENABLED=true
OTEL_SERVICE_NAME=full-stack-rag-template-api
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
```

`OTEL_SERVICE_NAME` must be non-empty. When `OBSERVABILITY_ENABLED=true`,
`OTEL_EXPORTER_OTLP_ENDPOINT` must also be non-empty and must be the complete OTLP/HTTP traces URL,
including `/v1/traces` when required by the receiver. Restart FastAPI after changing these values.

The adapter uses an OTLP/HTTP exporter and a batch span processor. Export therefore happens
asynchronously rather than delaying each API request. The FastAPI lifespan shuts down the local
tracer provider on exit, allowing its buffered spans to flush. The application neither configures
a global tracer provider nor exports metrics or logs.

### Local inspection

The reusable local Jaeger service is provisioned by the sibling `shared-observability` project,
not by this application repository. Start it with
`docker compose -f ../shared-observability/compose.yaml up -d`, then open
`http://localhost:16686`. Its official Jaeger image and persistent Badger volume are shared by
local applications; use a distinct `OTEL_SERVICE_NAME` for each application. Then:

1. enable observability with the settings above and start FastAPI;
2. upload a small document and ask it one question;
3. open the collector/backend's own trace UI;
4. filter by service `full-stack-rag-template-api`;
5. inspect `http.document.upload` and `http.document.question` traces and their nested `document.*`,
   `rag.*`, and `db.*` spans.

An upload should show extraction, chunking, one or more embedding batches, and chunk persistence. A
question with evidence should show query embedding, hybrid retrieval, generation, and question
event persistence. A no-evidence question omits generation. Because exporting is batched, allow a
short delay before concluding that a trace is missing, and stop FastAPI cleanly to flush at the end
of a session.

Do not expect or attempt to add document text, filenames, paths, questions, prompts, answers,
headers, credentials, or exception messages to make traces easier to search. The adapter rejects
known-sensitive attribute keys, and exception events contain only the exception type. The filter is
key-based, so new instrumentation must use count/status/model identifiers rather than sensitive
values under newly invented keys.

For deterministic tests, inject a `Tracer` implementation into `create_app` or the service under
test. `NoOpTracer` is appropriate when only behavior matters; an `OpenTelemetryTracer` with an
in-memory exporter is appropriate when asserting span names, parentage, attributes, error status,
flush, or shutdown behavior. Tests must not point at a real remote collector.

## Tests

Backend unit and integration tests are discovered below `backend/tests`. From `backend`:

```bash
uv run pytest tests/unit
uv run pytest tests/integration
uv run ruff check app tests
```

Database-backed integration tests require a disposable database URL in
`TEST_DATABASE_URL`. Tests skip rather than accidentally use the development database when it is
absent. The test URL must use an isolated database because migrations and row cleanup may modify
its contents.

After provisioning, the reference setup includes the isolated `rag_template_test` database:

```bash
make db-test-up
make test-integration
```

Use `make e2e-setup` once to install Playwright and Chromium, then `make test-e2e` for the browser
suite. The browser tests mock the HTTP contract and do not contact OpenAI or PostgreSQL.

Frontend tests run from `frontend` with the package scripts defined there. Browser tests live in
`tests/e2e` and require Playwright plus running backend/frontend servers configured to use
deterministic provider fakes. The coordinator owns root-level runner/configuration wiring.

### Testing layers

- **Unit:** configuration, parsers, chunking, fusion/ranking, service behavior, UI components.
- **Integration:** migrations, pgvector/full-text behavior, API lifecycle, file cleanup, provider
  fakes, and all supported document types.
- **End to end:** a browser uploads a document, selects it, asks a question, and sees a grounded
  answer with a citation.

Test fixtures contain invented text and no personal or confidential data. Integration and browser
tests must not make real OpenAI calls.

## Troubleshooting

- **Database connection refused:** start the standalone shared service, wait for its health check,
  and confirm it is published on host port 5434.
- **`vector` type missing:** apply the latest migrations against the pgvector image, not a plain
  PostgreSQL image.
- **Embedding dimension error:** set the configured dimension to the selected provider/model's
  output dimension and recreate or re-embed documents from an incompatible embedding space.
- **Upload accepted but no useful text:** the PDF may be scanned; OCR is not part of the MVP.
- **CORS failure:** ensure the exact frontend origin appears in `BACKEND_CORS_ORIGINS`.
- **Tests try to call OpenAI:** select the deterministic fake provider/test application setup;
  never put a real credential in test configuration.

## Contribution boundaries

Keep HTTP concerns out of retrieval code, provider SDK types behind interfaces, and database
queries in repository modules. Add a migration for schema changes and tests at the lowest useful
layer. Update the API or retrieval documentation when externally visible behavior changes.
