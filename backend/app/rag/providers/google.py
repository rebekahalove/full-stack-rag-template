from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

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
class GoogleChatConfig:
    model: str
    api_key: str
    base_url: str
    timeout_seconds: float
    temperature: float | None
    max_output_tokens: int | None


@dataclass(frozen=True, slots=True)
class GoogleEmbeddingConfig:
    model: str
    api_key: str
    dimensions: int
    document_task_type: str
    query_task_type: str
    base_url: str
    timeout_seconds: float


class GoogleAnswerProvider:
    def __init__(
        self,
        *,
        config: GoogleChatConfig,
        instructions: str,
        transport: AsyncJsonTransport | None = None,
    ) -> None:
        self.model_name = require_model(config.model, "google")
        self.instructions = instructions
        self._config = config
        self._api_key = require_api_key(config.api_key, "google")
        self._transport = transport or HttpxJsonTransport()

    async def answer(self, *, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        prompt = build_grounded_answer_prompt(
            question=question, context=context, instructions=self.instructions
        )
        generation: dict[str, Any] = {"responseMimeType": "application/json"}
        if self._config.temperature is not None:
            generation["temperature"] = self._config.temperature
        if self._config.max_output_tokens is not None:
            generation["maxOutputTokens"] = self._config.max_output_tokens
        payload = await self._transport.request_json(
            method="POST",
            url=(
                f"{self._config.base_url.rstrip('/')}/models/"
                f"{quote(self.model_name, safe='')}:generateContent"
            ),
            headers={"x-goog-api-key": self._api_key, "content-type": "application/json"},
            json_body={
                "systemInstruction": {"parts": [{"text": prompt.system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt.user}]}],
                "generationConfig": generation,
            },
            timeout_seconds=self._config.timeout_seconds,
        )
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            raw = "".join(str(part.get("text", "")) for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderResponseError("google response did not contain assistant text") from exc
        if not raw:
            raise ProviderResponseError("google response did not contain assistant text")
        return parse_generated_answer(raw)


class GoogleEmbeddingProvider:
    def __init__(
        self,
        *,
        config: GoogleEmbeddingConfig,
        transport: AsyncJsonTransport | None = None,
    ) -> None:
        self.model = require_model(config.model, "google")
        self.dimensions = require_dimensions(config.dimensions, "google")
        self._config = config
        self._api_key = require_api_key(config.api_key, "google")
        self._transport = transport or HttpxJsonTransport()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Legacy behavior embeds a document batch; prefer the purpose-specific methods."""
        return await self.embed_documents(texts)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, task_type=self._config.document_task_type)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text], task_type=self._config.query_task_type)
        return vectors[0]

    async def _embed(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        if not texts:
            return []
        model_path = f"models/{self.model}"
        payload = await self._transport.request_json(
            method="POST",
            url=(
                f"{self._config.base_url.rstrip('/')}/models/"
                f"{quote(self.model, safe='')}:batchEmbedContents"
            ),
            headers={"x-goog-api-key": self._api_key, "content-type": "application/json"},
            json_body={
                "requests": [
                    {
                        "model": model_path,
                        "content": {"parts": [{"text": text}]},
                        "taskType": task_type,
                        "outputDimensionality": self.dimensions,
                    }
                    for text in texts
                ]
            },
            timeout_seconds=self._config.timeout_seconds,
        )
        try:
            vectors = [[float(value) for value in item["values"]] for item in payload["embeddings"]]
        except (KeyError, TypeError) as exc:
            raise ProviderResponseError("google response did not contain embeddings") from exc
        return validate_embeddings(vectors, expected_count=len(texts), dimensions=self.dimensions)
