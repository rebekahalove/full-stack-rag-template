# Template customization checklist

Use this checklist immediately after creating a repository from `full-stack-rag-template`. Make
the identity and infrastructure choices before running migrations so the derived project never
shares application credentials, databases, or telemetry names with another project.

## 1. Choose the project identity

Record these values for the derived application:

| Purpose | Template value | Example derived value |
| --- | --- | --- |
| Repository and folder | `full-stack-rag-template` | `policy-assistant` |
| Backend display name | `Full-stack RAG Template API` | `Policy Assistant API` |
| Frontend display name | `RAG Workbench` | `Policy Assistant` |
| Short UI mark | `R` | `P` |
| PostgreSQL role | `rag_template` | `policy_assistant` |
| Development database | `rag_template` | `policy_assistant` |
| Test database | `rag_template_test` | `policy_assistant_test` |
| OpenTelemetry service | `full-stack-rag-template-api` | `policy-assistant-api` |
| OpenTelemetry tracer | `full-stack-rag-template` | `policy-assistant` |

The Python and npm package names are private implementation identifiers and may remain generic.
Rename them when the derived project will publish packages or when consistent artifact naming is
important.

## 2. Create local configuration

Copy the example file and edit the new, ignored file:

```bash
cp .env.example .env
```

At minimum, replace:

- `APP_NAME`, `APP_DESCRIPTION`, and `APP_VERSION`;
- `DATABASE_URL` and `TEST_DATABASE_URL`, including the role, password, and database names;
- `VITE_APP_NAME`, `VITE_APP_MARK`, `VITE_APP_TAGLINE`, and `VITE_APP_DESCRIPTION`;
- `OTEL_SERVICE_NAME` and `OTEL_TRACER_NAME`;
- the credentials and model selections for the chosen embedding and chat providers.

Never put shared PostgreSQL administrator credentials in this repository. Provider keys and local
application passwords belong only in `.env` or a deployment secret manager.

## 3. Provision isolated database resources

The reference launcher expects the reusable `postgresql-for-all-projects` container maintained by
the sibling `shared-postgresql` project. Provision one login role plus separate development and
test databases for the derived project from that infrastructure project. Do not reuse the
template's `rag_template` role or either template database across applications.

After updating `.env`, apply the complete schema:

```bash
make db-up
make migrate
```

The test database name must contain `test`; the integration harness deliberately rejects other
names before running migrations or cleanup.

## 4. Customize the product boundary

Review the reference application before treating it as production-ready:

- authentication, authorization, tenancy, and rate limiting are intentionally absent;
- uploaded files use local storage rather than managed object storage;
- processing runs in the API process rather than a durable job queue;
- exact document-scoped vector retrieval favors mixed embedding dimensions over a global ANN
  index;
- OCR, malware scanning, retention policies, and backup policies are application decisions;
- allowed document types, upload limits, prompts, and insufficient-evidence behavior are
  configuration rather than universal requirements.

Document every decision that changes these boundaries in the derived repository.

## 5. Replace or extend evaluation data

Keep `evaluation/datasets/example.json` and `evaluation/trials/example.json` as a fast harness
smoke test. The synthetic starter benchmark is useful for regression testing general document RAG,
but it is not a substitute for representative domain data.

Create a reviewed dataset and focused trials for the derived use case, then run:

```bash
make evaluate-smoke
make evaluate DATASET=evaluation/datasets/your-project.json \
  TRIALS=evaluation/trials/your-project.json
```

Do not place credentials, confidential source documents, or generated reports in version control.

## 6. Verify before the first project commit

Run the reusable checks:

```bash
make test-unit
make test-integration
make test-frontend
```

Then search for template identifiers that should not survive in a derived product:

```bash
rg -n 'full-stack-rag-template|rag_template|RAG Workbench' \
  .env.example README.md backend docs frontend tests
```

Occurrences in historical migration identifiers or documentation examples may be intentional;
review rather than blindly replacing them.

## 7. Publish and protect the repository

For the source repository, enable GitHub's **Template repository** setting. For a derived project,
protect `main`, require pull requests and status checks, and require at least one reviewer who is
not the account that authored the change.
