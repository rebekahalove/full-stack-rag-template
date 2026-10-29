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
    require_model,
)
from app.rag.providers.transport import HttpxJsonTransport
from app.rag.types import RetrievedChunk


@dataclass(frozen=True, slots=True)
class AnthropicConfig:
    model: str
    api_key: str
    max_tokens: int
    base_url: str
    api_version: str
    timeout_seconds: float
    temperature: float | None


class AnthropicAnswerProvider:
    def __init__(
        self,
        *,
        config: AnthropicConfig,
        instructions: str,
        transport: AsyncJsonTransport | None = None,
    ) -> None:
        self.model_name = require_model(config.model, "anthropic")
        self.instructions = instructions
        self._config = config
        self._api_key = require_api_key(config.api_key, "anthropic")
        self._transport = transport or HttpxJsonTransport()

    async def answer(self, *, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        prompt = build_grounded_answer_prompt(
            question=question, context=context, instructions=self.instructions
        )
        body: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self._config.max_tokens,
            "system": prompt.system,
            "messages": [{"role": "user", "content": prompt.user}],
        }
        if self._config.temperature is not None:
            body["temperature"] = self._config.temperature
        payload = await self._transport.request_json(
            method="POST",
            url=f"{self._config.base_url.rstrip('/')}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": self._config.api_version,
                "content-type": "application/json",
            },
            json_body=body,
            timeout_seconds=self._config.timeout_seconds,
        )
        blocks = payload.get("content")
        if not isinstance(blocks, list):
            raise ProviderResponseError("anthropic response did not contain content blocks")
        raw = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not raw:
            raise ProviderResponseError("anthropic response did not contain assistant text")
        return parse_generated_answer(raw)
