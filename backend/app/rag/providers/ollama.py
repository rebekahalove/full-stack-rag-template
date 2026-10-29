from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.rag.generation.providers import GeneratedAnswer
from app.rag.providers.common import (
    AsyncJsonTransport,
    ProviderResponseError,
    build_grounded_answer_prompt,
    parse_generated_answer,
    require_dimensions,
    require_model,
    validate_embeddings,
)
from app.rag.providers.transport import HttpxJsonTransport
from app.rag.types import RetrievedChunk


@dataclass(frozen=True, slots=True)
class OllamaChatConfig:
    model: str
    base_url: str
    timeout_seconds: float
    temperature: float | None
    max_output_tokens: int | None


@dataclass(frozen=True, slots=True)
class OllamaEmbeddingConfig:
    model: str
    dimensions: int
    base_url: str
    timeout_seconds: float


class OllamaAnswerProvider:
    def __init__(
        self,
        *,
        config: OllamaChatConfig,
        instructions: str,
        transport: AsyncJsonTransport | None = None,
    ) -> None:
        self.model_name = require_model(config.model, "ollama")
        self.instructions = instructions
        self._config = config
        self._transport = transport or HttpxJsonTransport()

    async def answer(self, *, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        prompt = build_grounded_answer_prompt(
            question=question, context=context, instructions=self.instructions
        )
        body: dict[str, Any] = {
            "model": self.model_name,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
        }
        options: dict[str, Any] = {}
        if self._config.temperature is not None:
            options["temperature"] = self._config.temperature
        if self._config.max_output_tokens is not None:
            options["num_predict"] = self._config.max_output_tokens
        if options:
            body["options"] = options
        payload = await self._transport.request_json(
            method="POST",
            url=f"{self._config.base_url.rstrip('/')}/api/chat",
            json_body=body,
            timeout_seconds=self._config.timeout_seconds,
        )
        try:
            raw = payload["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ProviderResponseError("ollama response did not contain assistant text") from exc
        if not isinstance(raw, str):
            raise ProviderResponseError("ollama response did not contain assistant text")
        return parse_generated_answer(raw)


class OllamaEmbeddingProvider:
    def __init__(
        self,
        *,
        config: OllamaEmbeddingConfig,
        transport: AsyncJsonTransport | None = None,
    ) -> None:
        self.model = require_model(config.model, "ollama")
        self.dimensions = require_dimensions(config.dimensions, "ollama")
        self._config = config
        self._transport = transport or HttpxJsonTransport()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.embed_documents(texts)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text])
        return vectors[0]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = await self._transport.request_json(
            method="POST",
            url=f"{self._config.base_url.rstrip('/')}/api/embed",
            json_body={"model": self.model, "input": texts},
            timeout_seconds=self._config.timeout_seconds,
        )
        try:
            vectors = [[float(value) for value in vector] for vector in payload["embeddings"]]
        except (KeyError, TypeError) as exc:
            raise ProviderResponseError("ollama response did not contain embeddings") from exc
        return validate_embeddings(vectors, expected_count=len(texts), dimensions=self.dimensions)
