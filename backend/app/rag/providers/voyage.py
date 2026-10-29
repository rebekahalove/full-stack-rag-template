from __future__ import annotations

from dataclasses import dataclass

from app.rag.providers.common import (
    AsyncJsonTransport,
    ProviderResponseError,
    require_api_key,
    require_dimensions,
    require_model,
    validate_embeddings,
)
from app.rag.providers.transport import HttpxJsonTransport


@dataclass(frozen=True, slots=True)
class VoyageEmbeddingConfig:
    model: str
    api_key: str
    dimensions: int
    document_input_type: str
    query_input_type: str
    base_url: str
    timeout_seconds: float


class VoyageEmbeddingProvider:
    def __init__(
        self,
        *,
        config: VoyageEmbeddingConfig,
        transport: AsyncJsonTransport | None = None,
    ) -> None:
        self.model = require_model(config.model, "voyage")
        self.dimensions = require_dimensions(config.dimensions, "voyage")
        self._config = config
        self._api_key = require_api_key(config.api_key, "voyage")
        self._transport = transport or HttpxJsonTransport()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.embed_documents(texts)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, input_type=self._config.document_input_type)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], input_type=self._config.query_input_type))[0]

    async def _embed(self, texts: list[str], *, input_type: str) -> list[list[float]]:
        if not texts:
            return []
        payload = await self._transport.request_json(
            method="POST",
            url=f"{self._config.base_url.rstrip('/')}/embeddings",
            headers={
                "authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
            json_body={
                "model": self.model,
                "input": texts,
                "input_type": input_type,
                "output_dimension": self.dimensions,
            },
            timeout_seconds=self._config.timeout_seconds,
        )
        try:
            ordered = sorted(payload["data"], key=lambda item: item.get("index", 0))
            vectors = [[float(value) for value in item["embedding"]] for item in ordered]
        except (KeyError, TypeError) as exc:
            raise ProviderResponseError("voyage response did not contain embeddings") from exc
        return validate_embeddings(vectors, expected_count=len(texts), dimensions=self.dimensions)


__all__ = ["VoyageEmbeddingConfig", "VoyageEmbeddingProvider"]
