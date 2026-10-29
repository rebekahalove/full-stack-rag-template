from __future__ import annotations

from typing import Any

import httpx

from app.rag.providers.common import ProviderResponseError


class HttpxJsonTransport:
    """Small injectable HTTP boundary shared by native provider adapters."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def request_json(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if self._client is not None:
            response = await self._client.request(
                method, url, headers=headers, json=json_body, timeout=timeout_seconds
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method, url, headers=headers, json=json_body, timeout=timeout_seconds
                )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderResponseError(
                f"provider request failed with HTTP {response.status_code}"
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProviderResponseError("provider returned a non-object JSON response")
        return payload
