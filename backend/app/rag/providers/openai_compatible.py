from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from app.rag.generation.providers import GeneratedAnswer
from app.rag.providers.common import (
    ProviderConfigurationError,
    ProviderResponseError,
    build_grounded_answer_prompt,
    parse_generated_answer,
    require_api_key,
    require_dimensions,
    require_model,
    validate_embeddings,
)
from app.rag.types import RetrievedChunk


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    model: str
    api_key: str
    base_url: str | None
    timeout_seconds: float
    extra_headers: dict[str, str] | None
    temperature: float | None
    max_tokens: int | None
    max_tokens_parameter: str
    send_json_response_format: bool


@dataclass(frozen=True, slots=True)
class OpenAICompatibleEmbeddingConfig:
    model: str
    api_key: str
    dimensions: int
    base_url: str | None
    timeout_seconds: float
    extra_headers: dict[str, str] | None
    send_dimensions: bool
    document_input_type: str | None
    query_input_type: str | None


class OpenAICompatibleAnswerProvider:
    """Chat-completions adapter for OpenAI and compatible API gateways/vendors."""

    def __init__(
        self,
        *,
        config: OpenAICompatibleConfig,
        instructions: str,
        client: Any | None = None,
    ) -> None:
        self.model_name = require_model(config.model, "openai-compatible provider")
        self.instructions = instructions
        self._config = config
        if config.max_tokens_parameter not in {"max_tokens", "max_completion_tokens"}:
            raise ProviderConfigurationError(
                "max_tokens_parameter must be max_tokens or max_completion_tokens"
            )
        api_key = require_api_key(config.api_key, "openai-compatible provider")
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            default_headers=config.extra_headers,
        )

    async def answer(self, *, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        prompt = build_grounded_answer_prompt(
            question=question, context=context, instructions=self.instructions
        )
        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
        }
        if self._config.send_json_response_format:
            kwargs["response_format"] = {"type": "json_object"}
        if self._config.temperature is not None:
            kwargs["temperature"] = self._config.temperature
        if self._config.max_tokens is not None:
            kwargs[self._config.max_tokens_parameter] = self._config.max_tokens
        response = await self.client.chat.completions.create(
            **kwargs,
        )
        try:
            raw = response.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise ProviderResponseError("provider response did not contain assistant text") from exc
        if not isinstance(raw, str):
            raise ProviderResponseError("provider response did not contain assistant text")
        return parse_generated_answer(raw)


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self, *, config: OpenAICompatibleEmbeddingConfig, client: Any | None = None
    ) -> None:
        self.model = require_model(config.model, "openai-compatible provider")
        self.dimensions = require_dimensions(config.dimensions, "openai-compatible provider")
        self.send_dimensions = config.send_dimensions
        self._config = config
        api_key = require_api_key(config.api_key, "openai-compatible provider")
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            default_headers=config.extra_headers,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Legacy behavior embeds a document batch; prefer the purpose-specific methods."""
        return await self.embed_documents(texts)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, input_type=self._config.document_input_type)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text], input_type=self._config.query_input_type)
        return vectors[0]

    async def _embed(self, texts: list[str], *, input_type: str | None) -> list[list[float]]:
        if not texts:
            return []
        kwargs: dict[str, Any] = {"model": self.model, "input": texts}
        if self.send_dimensions:
            kwargs["dimensions"] = self.dimensions
        if input_type is not None:
            kwargs["extra_body"] = {"input_type": input_type}
        response = await self.client.embeddings.create(**kwargs)
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = [[float(value) for value in item.embedding] for item in ordered]
        return validate_embeddings(vectors, expected_count=len(texts), dimensions=self.dimensions)
