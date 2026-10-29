# Provider and model selection

Embedding and chat providers are selected independently. This matters because some vendors offer
only one capability, and a strong RAG configuration often combines an embedding specialist with a
different generation model.

```dotenv
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536

CHAT_PROVIDER=openai
CHAT_MODEL=gpt-4.1-mini
```

Provider and model values can also be overridden per evaluation trial. Model IDs are deliberately
not enums: catalogs and aliases change, so configuration and reports retain the exact string sent
to the provider.

Some OpenAI-compatible reasoning models reject `temperature` or use
`max_completion_tokens` instead of `max_tokens`. Set `CHAT_SEND_TEMPERATURE=false` and/or
`CHAT_MAX_TOKENS_PARAMETER=max_completion_tokens` for those models; both values may also be trial
overrides.

## Adapter matrix

| Registry name | Embeddings | Chat | API style |
| --- | --- | --- | --- |
| `openai` | yes | yes | OpenAI-compatible |
| `anthropic` | no | yes | native Messages API |
| `google` | yes | yes | native Gemini API |
| `cohere` | yes | yes | native v2 API |
| `mistral` | yes | yes | OpenAI-compatible |
| `voyage` | yes | no | native embeddings API |
| `ollama` | yes | yes | native local API |
| `openrouter` | model-dependent | yes | OpenAI-compatible |
| `together` | model-dependent | yes | OpenAI-compatible |
| `groq` | no | yes | OpenAI-compatible |
| `openai_compatible` | endpoint-dependent | endpoint-dependent | custom gateway |

The native Google, Cohere, and Ollama adapters preserve vendor-specific request semantics. The
embedding interface distinguishes document embeddings from query embeddings. With `auto` task
modes, Google receives `RETRIEVAL_DOCUMENT`/`RETRIEVAL_QUERY`, Cohere receives
`search_document`/`search_query`, and Voyage receives `document`/`query`.

## Credentials and endpoints

Put credentials only in `.env`. Named keys include `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `COHERE_API_KEY`, `MISTRAL_API_KEY`, `VOYAGE_API_KEY`,
`OPENROUTER_API_KEY`, `TOGETHER_API_KEY`, and `GROQ_API_KEY`. Ollama normally needs no key.

`EMBEDDING_API_KEY`/`CHAT_API_KEY` and `EMBEDDING_BASE_URL`/`CHAT_BASE_URL` override the selected
provider's named values. These generic overrides are useful for proxies and private gateways.

## Vector compatibility

The application stores unconstrained pgvector `vector` values and records each row's actual
dimension, so supported providers do not have to emit 1,536 values. Never pad or truncate a model's
vectors: that changes their geometry and invalidates retrieval. Switching provider, model,
dimensions, endpoint, or asymmetric task modes requires re-embedding the corpus. Each uploaded
document stores a secret-free embedding-space fingerprint, and question answering refuses to mix
incompatible spaces.

The reusable template uses exact cosine search scoped to one document. A single HNSW index cannot
cover mixed vector dimensions, and pgvector's indexed-dimension limits do not transparently cover
every provider output. A production deployment that pins one embedding space may add a partial
expression index cast to its specific dimension in a deployment-specific migration. The offline
evaluation harness remains database-free and can compare dimensions before choosing that index.

## Primary documentation

- [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings)
- [Anthropic models and embedding guidance](https://platform.claude.com/docs/en/build-with-claude/embeddings)
- [Google Gemini embeddings](https://ai.google.dev/gemini-api/docs/embeddings)
- [Cohere Embed](https://docs.cohere.com/docs/cohere-embed)
- [Mistral embeddings](https://docs.mistral.ai/studio/knowledge-rag/embeddings/text_embeddings)
- [Voyage embeddings](https://docs.voyageai.com/docs/embeddings)
- [Ollama embedding API](https://docs.ollama.com/api/embed)
- [OpenRouter developer platform](https://openrouter.ai/developers)
- [Together OpenAI compatibility](https://docs.together.ai/docs/inference/openai-compatibility)
