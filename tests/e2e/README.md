# Browser tests

These tests exercise the primary React workflow with deterministic network fixtures. They never
contact OpenAI and do not require PostgreSQL; database-backed behavior belongs to the backend
integration suite. Coverage includes the upload-and-question path, insufficient evidence, and the
same-session failed-ingestion cleanup path in which deleting the persisted failed document clears
the matching staged filename and upload error.

From this directory:

```bash
npm install
npx playwright install chromium
npm test
```

By default Playwright starts the frontend development server. Set `E2E_BASE_URL` to test an already
running frontend. The request fixtures assume the stable API contract in `../../docs/contracts.md`.
