from typing import Any

import pytest

from app.rag.providers.voyage import VoyageEmbeddingConfig, VoyageEmbeddingProvider


class RecordingTransport:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def request_json(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        values = request["json_body"]["input"]
        return {
            "data": [
                {"index": index, "embedding": [float(index), 1.0]} for index, _ in enumerate(values)
            ]
        }


@pytest.mark.asyncio
async def test_voyage_uses_native_dimension_and_purpose_fields() -> None:
    transport = RecordingTransport()
    provider = VoyageEmbeddingProvider(
        config=VoyageEmbeddingConfig(
            model="voyage-test",
            api_key="secret",
            dimensions=2,
            document_input_type="document",
            query_input_type="query",
            base_url="https://voyage.invalid/v1",
            timeout_seconds=10,
        ),
        transport=transport,
    )

    documents = await provider.embed_documents(["first", "second"])
    query = await provider.embed_query("question")

    assert documents == [[0.0, 1.0], [1.0, 1.0]]
    assert query == [0.0, 1.0]
    assert transport.requests[0]["json_body"]["input_type"] == "document"
    assert transport.requests[1]["json_body"]["input_type"] == "query"
    assert transport.requests[0]["json_body"]["output_dimension"] == 2
