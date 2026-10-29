from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.rag.generation.providers import GeneratedAnswer
from app.rag.providers.common import (
    AsyncJsonTransport,
    ProviderResponseError,
    build_grounded_answer_prompt,
    parse_generated_answer,
    require_api_key,
    require_dimensions,
    require_model,
    validate_embeddings,
)
from app.rag.providers.transport import HttpxJsonTransport
from app.rag.types import RetrievedChunk


@dataclass(frozen=True, slots=True)
class CohereChatConfig:
    model: str
    api_key: str
    max_tokens: int | None
    temperature: float | None
    base_url: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class CohereEmbeddingConfig:
    model: str
    api_key: str
    dimensions: int
    document_input_type: str
    query_input_type: str
    embedding_type: str
    base_url: str
    timeout_seconds: float


class CohereAnswerProvider:
    def __init__(
        self,
        *,
        config: CohereChatConfig,
        instructions: str,
        transport: AsyncJsonTransport | None = None,
    ) -> None:
        self.model_name = require_model(config.model, "cohere")
        self.instructions = instructions
        self._config = config
        self._api_key = require_api_key(config.api_key, "cohere")
        self._transport = transport or HttpxJsonTransport()

    async def answer(self, *, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        prompt = build_grounded_answer_prompt(
            question=question, context=context, instructions=self.instructions
        )
        body: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "response_format": {"type": "json_object"},
        }
        if self._config.max_tokens is not None:
            body["max_tokens"] = self._config.max_tokens
        if self._config.temperature is not None:
            body["temperature"] = self._config.temperature
        payload = await self._transport.request_json(
            method="POST",
            url=f"{self._config.base_url.rstrip('/')}/v2/chat",
            headers={
                "authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
            json_body=body,
            timeout_seconds=self._config.timeout_seconds,
        )
        try:
            content = payload["message"]["content"]
            raw = "".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise ProviderResponseError("cohere response did not contain assistant text") from exc
        if not raw:
            raise ProviderResponseError("cohere response did not contain assistant text")
        return parse_generated_answer(raw)


class CohereEmbeddingProvider:
    def __init__(
        self,
        *,
        config: CohereEmbeddingConfig,
        transport: AsyncJsonTransport | None = None,
    ) -> None:
        self.model = require_model(config.model, "cohere")
        self.dimensions = require_dimensions(config.dimensions, "cohere")
        self._config = config
        self._api_key = require_api_key(config.api_key, "cohere")
        self._transport = transport or HttpxJsonTransport()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Legacy behavior embeds a document batch; prefer the purpose-specific methods."""
        return await self.embed_documents(texts)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, input_type=self._config.document_input_type)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text], input_type=self._config.query_input_type)
        return vectors[0]

    async def _embed(self, texts: list[str], *, input_type: str) -> list[list[float]]:
        if not texts:
            return []
        payload = await self._transport.request_json(
            method="POST",
            url=f"{self._config.base_url.rstrip('/')}/v2/embed",
            headers={
                "authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
            json_body={
                "model": self.model,
                "texts": texts,
                "input_type": input_type,
                "embedding_types": [self._config.embedding_type],
                "output_dimension": self.dimensions,
            },
            timeout_seconds=self._config.timeout_seconds,
        )
        try:
            raw_vectors = payload["embeddings"][self._config.embedding_type]
            vectors = [[float(value) for value in vector] for vector in raw_vectors]
        except (KeyError, TypeError) as exc:
            raise ProviderResponseError("cohere response did not contain embeddings") from exc
        return validate_embeddings(vectors, expected_count=len(texts), dimensions=self.dimensions)
