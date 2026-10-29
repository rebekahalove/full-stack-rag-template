# Modular RAG evaluation

The evaluation harness compares complete RAG configurations without writing documents, chunks,
embeddings, or question events to the application database. Its concrete offline runner exercises
the same extraction, structure-aware chunking, embedding-provider, and answer-provider interfaces
as the application, then performs hybrid retrieval entirely in memory.

## What is evaluated

The default deterministic metrics are grouped by pipeline component:

| Component | Metrics |
| --- | --- |
| Parsing | Expected-keyword recall in extracted text |
| Chunking | Keyword coverage and expected-source cohesion within chunks |
| Retrieval | Source recall, source precision, and mean reciprocal rank |
| Generation | Citation recall/precision, answer-keyword recall, reference-answer token F1, and abstention accuracy |
| End to end | Geometric mean of available answer and citation signals |

Metrics with no corresponding ground truth are marked not applicable and omitted from aggregates.
No LLM judge is required for the default suite, so repeated evaluations are reproducible and do not
add judge-model cost. A custom evaluator implements `EvaluationMetric` and can be passed to
`EvaluationHarness` when semantic or model-graded scoring is desired.

## Dataset format

JSON datasets have a mandatory schema version and one or more documents. A document may refer to a
file relative to the dataset or contain inline text. Each expected source is identified by stable
metadata and/or required content keywords. A source ID may additionally narrow the match, but it
cannot be the only predicate because generated chunk IDs change meaning across chunking trials.

```json
{
  "schema_version": "1.0",
  "name": "employee-handbook",
  "description": "Questions with reviewed answers and source expectations",
  "documents": [
    {
      "id": "benefits-handbook",
      "path": "documents/benefits.md",
      "media_type": "text/markdown",
      "expected_keywords": ["medical coverage", "eligibility"],
      "metadata": {"corpus": "handbook"},
      "questions": [
        {
          "id": "coverage-start",
          "question": "When does medical coverage begin?",
          "reference_answers": ["Medical coverage begins on the employee's first day."],
          "expected_answer_keywords": ["first day"],
          "expected_insufficient_evidence": false,
          "expected_sources": [
            {
              "metadata": {"heading_path": ["Benefits", "Medical"]},
              "keywords": ["coverage", "first day"]
            }
          ]
        }
      ]
    }
  ]
}
```

JSONL is supported for large corpora. Its first record is the dataset header; every following record
is one complete document:

```jsonl
{"type":"dataset","schema_version":"1.0","name":"employee-handbook"}
{"type":"document","id":"benefits","path":"documents/benefits.md","questions":[{"id":"q1","question":"When does coverage begin?"}]}
```

## Trial format and tuning

A trial is a full parameter/model variant. Secret API keys never belong in a trial file; provider
factories read those from the environment. Trial parameters use stable dotted names so reports remain
comparable even when application setting names evolve.

```json
{
  "schema_version": "1.0",
  "trials": [
    {
      "id": "openai-small-600",
      "tags": ["baseline"],
      "parameters": {
        "embeddings.provider": "openai",
        "embeddings.model": "text-embedding-3-small",
        "embeddings.dimensions": 1536,
        "generation.provider": "openai",
        "generation.model": "gpt-4.1-mini",
        "chunking.target_tokens": 600,
        "retrieval.final_count": 6
      }
    },
    {
      "id": "cohere-anthropic-800",
      "parameters": {
        "embeddings.provider": "cohere",
        "embeddings.model": "embed-v4.0",
        "generation.provider": "anthropic",
        "generation.model": "claude-sonnet",
        "chunking.target_tokens": 800,
        "retrieval.final_count": 8
      }
    }
  ]
}
```

The offline runner recognizes these pipeline overrides:

- `parsing.pdf_repeated_edge_min_pages`
- `parsing.pdf_repeated_edge_min_occurrences`
- `parsing.pdf_heading_max_characters`
- `chunking.target_tokens`, `chunking.min_tokens`, `chunking.max_tokens`
- `chunking.overlap_tokens`, `chunking.tokenizer_model`
- `chunking.tokenizer_fallback_encoding`
- `embeddings.batch_size`
- `retrieval.candidates_per_method`, `retrieval.final_count`
- `retrieval.rrf_k`, `retrieval.near_duplicate_threshold`

Embedding and answer provider factories receive the entire `ParameterTrial`, so they can consume
`embeddings.provider`, `embeddings.model`, `embeddings.dimensions`, `embeddings.base_url`,
`embeddings.document_input_type`, `embeddings.query_input_type`, `generation.provider`,
`generation.model`, `generation.base_url`, `generation.temperature`,
`generation.max_output_tokens`, and `generation.system_instructions` without coupling the harness
to a provider SDK. `expand_parameter_grid` creates a deterministic Cartesian sweep when exhaustive
parameter tuning is preferred over a hand-authored trial list.

Unknown trial keys are rejected rather than silently falling back to the baseline. The evaluator
also validates chunk/retrieval constraints before making provider calls and records the resolved,
secret-free pipeline/provider configuration in its JSON report.

## Application adapter

The one integration hook is an `EvaluationRunnerFactory`. The application should expose a callable
at an importable path, for example `app.evaluation_wiring:create_runner`. It receives a trial and
returns a runner. The provided `OfflinePipelineRunnerFactory` only needs:

1. An `OfflinePipelineConfig` populated from the application's normal parser, chunker, embedding,
   and retrieval settings.
2. An embedding-provider factory that reads provider/model/dimension overrides from the trial and
   credentials from environment-backed settings.
3. An answer-provider factory that reads provider/model/base-URL overrides from the trial and
   credentials from environment-backed settings.

The baseline mapping should use the existing application keys:

```text
PARSER_PDF_REPEATED_EDGE_MIN_PAGES
PARSER_PDF_REPEATED_EDGE_MIN_OCCURRENCES
PARSER_PDF_HEADING_MAX_CHARACTERS
CHUNK_TARGET_TOKENS
CHUNK_MIN_TOKENS
CHUNK_MAX_TOKENS
CHUNK_OVERLAP_TOKENS
TOKENIZER_FALLBACK_ENCODING
EMBEDDING_BATCH_SIZE
RETRIEVAL_CANDIDATES_PER_METHOD
RETRIEVAL_FINAL_COUNT
RETRIEVAL_RRF_K
RETRIEVAL_NEAR_DUPLICATE_THRESHOLD
```

Provider integration additionally exposes environment-backed provider, model, dimension,
base-URL, and credential keys. Dataset, trial, output, and ranking inputs are CLI arguments.
Paid-run safety limits are configured with:

```text
EVALUATION_MAX_TRIALS
EVALUATION_MAX_QUESTIONS
EVALUATION_TIMEOUT_SECONDS
```

## Running evaluations

Run the small example first to verify credentials, provider connectivity, parsing, and report
generation:

```bash
make evaluate-smoke
```

This uses `evaluation/datasets/example.json` and `evaluation/trials/example.json`, and writes
`.evaluation/smoke-results.json` plus `.evaluation/smoke-summary.md`. The smoke case verifies that
the harness runs; its tiny corpus is not evidence that a configuration is good for production.

The default general-purpose template benchmark uses the larger starter dataset and the focused
chunking trial suite:

```bash
make evaluate
```

That is equivalent to:

```bash
make evaluate \
  DATASET=evaluation/datasets/starter-general.json \
  TRIALS=evaluation/trials/chunking.json
```

Use the same starter corpus to tune one subsystem at a time:

```bash
# Retrieval candidate counts, result counts, fusion, and deduplication
make evaluate TRIALS=evaluation/trials/retrieval.json

# Provider/model examples; requires credentials for every provider selected
make evaluate TRIALS=evaluation/trials/models.example.json

# A project-specific benchmark and trial matrix
make evaluate \
  DATASET=evaluation/datasets/my-project.json \
  TRIALS=evaluation/trials/my-project.json
```

Report names are derived from the two inputs. For example, the default run writes
`.evaluation/starter-general-chunking-results.json` and
`.evaluation/starter-general-chunking-summary.md`, so it does not overwrite the smoke report.
Customize the name or paths when needed:

```bash
make evaluate \
  EVALUATION_RUN_NAME=retrieval-finalist \
  JSON_OUTPUT=.evaluation/archive/retrieval-finalist.json \
  MARKDOWN_OUTPUT=.evaluation/archive/retrieval-finalist.md
```

Missing dataset and trial files fail before any provider calls are made. API keys remain in the
root `.env`; datasets, trials, commands, and reports must not contain credentials. Use
`EVALUATION_ARGS` for optional CLI flags, such as safety-limit overrides or metric weights:

```bash
make evaluate \
  EVALUATION_ARGS='--weight retrieval.recall=3 --weight end_to_end.grounded_answer=5'
```

Ranking defaults to equal weight for every applicable metric. At the lower-level CLI, repeat
`--weight` to define an explicit objective, for example:

```bash
--weight retrieval.recall=3 --weight end_to_end.grounded_answer=5
```

Each safety limit has a corresponding CLI override. `EVALUATION_MAX_QUESTIONS` counts dataset
questions multiplied by trials. Provider dashboards remain the source of truth for token spend
because the adapters do not yet normalize provider-specific billing usage.

The offline keyword candidate stage excludes zero-overlap chunks and shares production's RRF and
near-duplicate behavior, but it remains a token-overlap approximation of PostgreSQL
`websearch_to_tsquery`. Use the PostgreSQL integration path before promoting finely separated
retrieval settings whose ranking depends on stemming or advanced full-text query syntax.

The JSON report retains per-document and per-question metrics, metric details, stage timings,
component aggregates, trial parameters, errors, and the final ranking. The Markdown report provides
an at-a-glance ranking followed by readable component, metric, parameter, timing, and error details
for each trial.
