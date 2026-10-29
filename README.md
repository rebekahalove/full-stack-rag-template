# Full-stack RAG template

A reusable, local-first starting point for document-grounded RAG applications. The included
reference application uploads PDF, DOCX, and Markdown documents and answers questions about one
selected document. The backend uses FastAPI, PostgreSQL full-text search, and pgvector; the
frontend uses React and TypeScript.

## Features

- Structure-aware extraction and configurable token chunking
- Hybrid vector and keyword retrieval with reciprocal-rank fusion
- Source metadata and citations retained through answer generation
- Replaceable embedding and answer providers with deterministic test doubles
- Offline evaluation trials for parsing, chunking, retrieval, embeddings, and generation
- Safe file handling, explicit insufficient-evidence answers, and prompt-injection boundaries
- Unit, API integration, PostgreSQL/pgvector integration, frontend, and browser tests

## Using this template

Create a repository from this template, then follow the
[template customization checklist](docs/template-customization.md) before provisioning project
resources. The checklist identifies the intentionally generic application, database, telemetry,
and package names that each derived project should replace. Evaluation fixtures remain synthetic
and can be kept as a regression baseline or replaced with a domain-specific benchmark.

## Quick start

Prerequisites are Python 3.12+, `uv`, Node.js 20+, npm, a PostgreSQL service with pgvector, and
(when tracing is enabled) an OTLP-compatible trace backend such as Jaeger. The reference local
topology uses the reusable sibling services described in the development guide.

```bash
cp .env.example .env
# Add credentials for the embedding and chat providers selected in .env.
make db-up
cd backend && uv sync --dev && uv run alembic upgrade head
```

The database service lives outside this repository in the sibling `shared-postgresql` project.
The reference configuration uses the dedicated `rag_template` role plus the `rag_template` and
`rag_template_test` databases. A derived project must choose unique resource names before
provisioning them. Host-run applications connect through `localhost:5434`; containers can join
the `postgresql-for-all-projects-network` Docker network.

For normal development, start the shared containers, apply migrations, and launch both web
services with:

```bash
make dev-start
```

Use `make dev-restart` to restart both web services, `make dev-status` to inspect everything, and
`make dev-stop` to stop only this application's web services. Shared PostgreSQL and Jaeger remain
running because other projects may be using them. Open `http://localhost:5173` after startup.

To verify the evaluation harness with its small example, then run the general starter benchmark:

```bash
make evaluate-smoke
make evaluate
```

Evaluation inputs are configurable without editing the Makefile:

```bash
make evaluate \
  DATASET=evaluation/datasets/starter-general.json \
  TRIALS=evaluation/trials/retrieval.json
```

Reports are written under `.evaluation/` with names derived from the selected dataset and trial
suite. See the evaluation guide for the benchmark layout, model trials, scoring, and safeguards.

For the complete setup, test commands, design, and API contract, see:

- [Development guide](docs/development.md)
- [Template customization](docs/template-customization.md)
- [Configuration reference](docs/configuration.md)
- [Shared PostgreSQL instance](docs/shared-postgresql.md)
- [Architecture](docs/architecture.md)
- [API reference](docs/api.md)
- [Retrieval design](docs/retrieval.md)
- [Provider selection](docs/providers.md)
- [Evaluation and tuning](docs/evaluation.md)

The reference application has no user authentication and is intended for trusted local
development until a derived project adds its own identity and authorization model.
