from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.rag.embeddings.providers import EmbeddingProvider
from app.rag.generation.providers import AnswerProvider
from app.rag.providers.anthropic import AnthropicAnswerProvider, AnthropicConfig
from app.rag.providers.cohere import (
    CohereAnswerProvider,
    CohereChatConfig,
    CohereEmbeddingConfig,
    CohereEmbeddingProvider,
)
from app.rag.providers.common import AsyncJsonTransport, ProviderConfigurationError
from app.rag.providers.google import (
    GoogleAnswerProvider,
    GoogleChatConfig,
    GoogleEmbeddingConfig,
    GoogleEmbeddingProvider,
)
from app.rag.providers.ollama import (
    OllamaAnswerProvider,
    OllamaChatConfig,
    OllamaEmbeddingConfig,
    OllamaEmbeddingProvider,
)
from app.rag.providers.openai_compatible import (
    OpenAICompatibleAnswerProvider,
    OpenAICompatibleConfig,
    OpenAICompatibleEmbeddingConfig,
    OpenAICompatibleEmbeddingProvider,
)
from app.rag.providers.voyage import VoyageEmbeddingConfig, VoyageEmbeddingProvider

AnswerConfig = (
    OpenAICompatibleConfig
    | AnthropicConfig
    | GoogleChatConfig
    | CohereChatConfig
    | OllamaChatConfig
)
EmbeddingConfig = (
    OpenAICompatibleEmbeddingConfig
    | GoogleEmbeddingConfig
    | CohereEmbeddingConfig
    | OllamaEmbeddingConfig
    | VoyageEmbeddingConfig
)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    name: str
    api_style: str
    chat: bool
    embeddings: bool
    asymmetric_embeddings: bool = False
    notes: str = ""


PROVIDER_CAPABILITIES: dict[str, ProviderCapabilities] = {
    "openai_compatible": ProviderCapabilities(
        "openai_compatible",
        "openai-compatible",
        True,
        True,
        True,
        "Capabilities depend on the selected endpoint and model.",
    ),
    "openai": ProviderCapabilities("openai", "openai-compatible", True, True),
    "azure_openai": ProviderCapabilities(
        "azure_openai",
        "openai-compatible",
        True,
        True,
        notes="Requires an OpenAI-compatible Azure gateway/base URL and headers.",
    ),
    "groq": ProviderCapabilities("groq", "openai-compatible", True, False, notes="Chat only."),
    "together": ProviderCapabilities("together", "openai-compatible", True, True),
    "mistral": ProviderCapabilities("mistral", "openai-compatible", True, True),
    "openrouter": ProviderCapabilities(
        "openrouter",
        "openai-compatible",
        True,
        True,
        True,
        notes="Capabilities and input modes depend on the selected routed model.",
    ),
    "voyage": ProviderCapabilities(
        "voyage",
        "voyage",
        False,
        True,
        True,
        "Embeddings only; configure document/query input types.",
    ),
    "anthropic": ProviderCapabilities("anthropic", "anthropic", True, False, notes="Chat only."),
    "google": ProviderCapabilities("google", "gemini", True, True, True),
    "cohere": ProviderCapabilities("cohere", "cohere", True, True, True),
    "ollama": ProviderCapabilities("ollama", "ollama", True, True),
}

_OPENAI_COMPATIBLE_CHAT = {
    "openai_compatible",
    "openai",
    "azure_openai",
    "groq",
    "together",
    "mistral",
    "openrouter",
}
_OPENAI_COMPATIBLE_EMBEDDINGS = {
    "openai_compatible",
    "openai",
    "azure_openai",
    "together",
    "mistral",
    "openrouter",
}


def create_answer_provider(
    provider: str,
    *,
    config: AnswerConfig,
    instructions: str,
    client: Any | None = None,
    transport: AsyncJsonTransport | None = None,
) -> AnswerProvider:
    name = _normalize(provider)
    if name in _OPENAI_COMPATIBLE_CHAT:
        _require_config(name, config, OpenAICompatibleConfig)
        return OpenAICompatibleAnswerProvider(
            config=config, instructions=instructions, client=client
        )
    if name == "anthropic":
        _require_config(name, config, AnthropicConfig)
        return AnthropicAnswerProvider(
            config=config, instructions=instructions, transport=transport
        )
    if name == "google":
        _require_config(name, config, GoogleChatConfig)
        return GoogleAnswerProvider(config=config, instructions=instructions, transport=transport)
    if name == "cohere":
        _require_config(name, config, CohereChatConfig)
        return CohereAnswerProvider(config=config, instructions=instructions, transport=transport)
    if name == "ollama":
        _require_config(name, config, OllamaChatConfig)
        return OllamaAnswerProvider(config=config, instructions=instructions, transport=transport)
    capability = PROVIDER_CAPABILITIES.get(name)
    if capability is not None and not capability.chat:
        raise ProviderConfigurationError(f"provider {name!r} does not support chat")
    raise ProviderConfigurationError(f"unknown answer provider {name!r}")


def create_embedding_provider(
    provider: str,
    *,
    config: EmbeddingConfig,
    client: Any | None = None,
    transport: AsyncJsonTransport | None = None,
) -> EmbeddingProvider:
    name = _normalize(provider)
    if name in _OPENAI_COMPATIBLE_EMBEDDINGS:
        _require_config(name, config, OpenAICompatibleEmbeddingConfig)
        return OpenAICompatibleEmbeddingProvider(config=config, client=client)
    if name == "google":
        _require_config(name, config, GoogleEmbeddingConfig)
        return GoogleEmbeddingProvider(config=config, transport=transport)
    if name == "cohere":
        _require_config(name, config, CohereEmbeddingConfig)
        return CohereEmbeddingProvider(config=config, transport=transport)
    if name == "ollama":
        _require_config(name, config, OllamaEmbeddingConfig)
        return OllamaEmbeddingProvider(config=config, transport=transport)
    if name == "voyage":
        _require_config(name, config, VoyageEmbeddingConfig)
        return VoyageEmbeddingProvider(config=config, transport=transport)
    capability = PROVIDER_CAPABILITIES.get(name)
    if capability is not None and not capability.embeddings:
        raise ProviderConfigurationError(f"provider {name!r} does not support embeddings")
    raise ProviderConfigurationError(f"unknown embedding provider {name!r}")


def _normalize(provider: str) -> str:
    return provider.strip().casefold().replace("-", "_")


def _require_config(name: str, config: object, expected: type) -> None:
    if not isinstance(config, expected):
        raise ProviderConfigurationError(
            f"provider {name!r} requires {expected.__name__}, got {type(config).__name__}"
        )
