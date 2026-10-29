from __future__ import annotations

import hashlib
import json

from pydantic import SecretStr

from app.core.config import Settings
from app.rag.embeddings import EmbeddingProvider
from app.rag.generation import AnswerProvider
from app.rag.providers import (
    AnthropicConfig,
    CohereChatConfig,
    CohereEmbeddingConfig,
    GoogleChatConfig,
    GoogleEmbeddingConfig,
    OllamaChatConfig,
    OllamaEmbeddingConfig,
    OpenAICompatibleConfig,
    OpenAICompatibleEmbeddingConfig,
    ProviderConfigurationError,
    VoyageEmbeddingConfig,
    create_answer_provider,
    create_embedding_provider,
)

_PROVIDER_SETTING_PREFIX = {
    "azure_openai": "openai_compatible",
    "openai_compatible": "openai_compatible",
}


def _normalize(provider: str) -> str:
    return provider.strip().casefold().replace("-", "_")


def _secret_value(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    result = value.get_secret_value().strip()
    return result or None


def _provider_value(settings: Settings, provider: str, suffix: str) -> object:
    prefix = _PROVIDER_SETTING_PREFIX.get(provider, provider)
    name = f"{prefix}_{suffix}"
    if not hasattr(settings, name):
        raise ProviderConfigurationError(
            f"provider {provider!r} has no configured {suffix.replace('_', ' ')}"
        )
    return getattr(settings, name)


def _api_key(settings: Settings, provider: str, override: SecretStr | None) -> str:
    if provider == "ollama":
        return _secret_value(override) or _secret_value(settings.ollama_api_key) or "ollama"
    selected = _secret_value(override)
    if selected is None:
        if provider == "google":
            selected = _secret_value(settings.google_api_key) or _secret_value(
                settings.gemini_api_key
            )
    if selected is None:
        provider_key = _provider_value(settings, provider, "api_key")
        selected = _secret_value(provider_key)  # type: ignore[arg-type]
    if selected is None:
        env_name = f"{_PROVIDER_SETTING_PREFIX.get(provider, provider).upper()}_API_KEY"
        raise ProviderConfigurationError(f"{env_name} or a generic API key override is required")
    return selected


def _base_url(settings: Settings, provider: str, override: str | None) -> str:
    selected = (override or "").strip()
    if not selected:
        selected = str(_provider_value(settings, provider, "base_url")).strip()
    if not selected:
        raise ProviderConfigurationError(f"a base URL is required for provider {provider!r}")
    return selected


def _purpose(provider: str, configured: str, *, document: bool) -> str | None:
    value = configured.strip()
    if value.casefold() != "auto":
        return value or None
    if provider == "google":
        return "RETRIEVAL_DOCUMENT" if document else "RETRIEVAL_QUERY"
    if provider == "cohere":
        return "search_document" if document else "search_query"
    if provider == "voyage":
        return "document" if document else "query"
    return None


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    provider = _normalize(settings.embedding_provider)
    key = _api_key(settings, provider, settings.embedding_api_key)
    base_url = _base_url(settings, provider, settings.embedding_base_url)
    document_type = _purpose(provider, settings.embedding_document_input_type, document=True)
    query_type = _purpose(provider, settings.embedding_query_input_type, document=False)
    if provider == "google":
        config = GoogleEmbeddingConfig(
            model=settings.embedding_model,
            api_key=key,
            dimensions=settings.embedding_dimensions,
            document_task_type=document_type or "RETRIEVAL_DOCUMENT",
            query_task_type=query_type or "RETRIEVAL_QUERY",
            base_url=base_url,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
    elif provider == "cohere":
        config = CohereEmbeddingConfig(
            model=settings.embedding_model,
            api_key=key,
            dimensions=settings.embedding_dimensions,
            document_input_type=document_type or "search_document",
            query_input_type=query_type or "search_query",
            embedding_type="float",
            base_url=base_url,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
    elif provider == "ollama":
        config = OllamaEmbeddingConfig(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            base_url=base_url,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
    elif provider == "voyage":
        config = VoyageEmbeddingConfig(
            model=settings.embedding_model,
            api_key=key,
            dimensions=settings.embedding_dimensions,
            document_input_type=document_type or "document",
            query_input_type=query_type or "query",
            base_url=base_url,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
    else:
        config = OpenAICompatibleEmbeddingConfig(
            model=settings.embedding_model,
            api_key=key,
            dimensions=settings.embedding_dimensions,
            base_url=base_url,
            timeout_seconds=settings.embedding_timeout_seconds,
            extra_headers=None,
            send_dimensions=settings.embedding_send_dimensions,
            document_input_type=document_type,
            query_input_type=query_type,
        )
    result = create_embedding_provider(provider, config=config)
    result.embedding_space_identity = embedding_space(settings)  # type: ignore[attr-defined]
    return result


def build_answer_provider(settings: Settings) -> AnswerProvider:
    provider = _normalize(settings.chat_provider)
    key = _api_key(settings, provider, settings.chat_api_key)
    base_url = _base_url(settings, provider, settings.chat_base_url)
    if provider == "anthropic":
        config = AnthropicConfig(
            model=settings.chat_model,
            api_key=key,
            max_tokens=settings.chat_max_output_tokens,
            base_url=base_url,
            api_version=settings.anthropic_api_version,
            timeout_seconds=settings.chat_timeout_seconds,
            temperature=(settings.chat_temperature if settings.chat_send_temperature else None),
        )
    elif provider == "google":
        config = GoogleChatConfig(
            model=settings.chat_model,
            api_key=key,
            base_url=base_url,
            timeout_seconds=settings.chat_timeout_seconds,
            temperature=(settings.chat_temperature if settings.chat_send_temperature else None),
            max_output_tokens=settings.chat_max_output_tokens,
        )
    elif provider == "cohere":
        config = CohereChatConfig(
            model=settings.chat_model,
            api_key=key,
            max_tokens=settings.chat_max_output_tokens,
            temperature=(settings.chat_temperature if settings.chat_send_temperature else None),
            base_url=base_url,
            timeout_seconds=settings.chat_timeout_seconds,
        )
    elif provider == "ollama":
        config = OllamaChatConfig(
            model=settings.chat_model,
            base_url=base_url,
            timeout_seconds=settings.chat_timeout_seconds,
            temperature=(settings.chat_temperature if settings.chat_send_temperature else None),
            max_output_tokens=settings.chat_max_output_tokens,
        )
    else:
        config = OpenAICompatibleConfig(
            model=settings.chat_model,
            api_key=key,
            base_url=base_url,
            timeout_seconds=settings.chat_timeout_seconds,
            extra_headers=None,
            temperature=(settings.chat_temperature if settings.chat_send_temperature else None),
            max_tokens=settings.chat_max_output_tokens,
            max_tokens_parameter=settings.chat_max_tokens_parameter,
            send_json_response_format=settings.chat_send_json_response_format,
        )
    return create_answer_provider(
        provider, config=config, instructions=settings.generation_system_instructions
    )


def embedding_space(settings: Settings) -> dict[str, object]:
    """Return a secret-free identity for vectors that may safely share an index."""
    provider = _normalize(settings.embedding_provider)
    endpoint = _base_url(settings, provider, settings.embedding_base_url)
    descriptor: dict[str, object] = {
        "provider": provider,
        "model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "endpoint_id": hashlib.sha256(endpoint.encode()).hexdigest()[:12],
        "document_input_type": _purpose(
            provider, settings.embedding_document_input_type, document=True
        ),
        "query_input_type": _purpose(provider, settings.embedding_query_input_type, document=False),
    }
    canonical = json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
    descriptor["id"] = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return descriptor


def embedding_space_for_provider(provider: EmbeddingProvider) -> dict[str, object]:
    """Identify the actual provider instance, including injected evaluation/test providers."""
    declared = getattr(provider, "embedding_space_identity", None)
    if isinstance(declared, dict) and isinstance(declared.get("id"), str):
        return dict(declared)
    config = getattr(provider, "_config", None)
    endpoint = str(getattr(config, "base_url", ""))
    descriptor: dict[str, object] = {
        "provider": getattr(provider, "provider_name", type(provider).__name__),
        "model": getattr(provider, "model", type(provider).__name__),
        "dimensions": getattr(provider, "dimensions", None),
        "endpoint_id": (hashlib.sha256(endpoint.encode()).hexdigest()[:12] if endpoint else None),
        "document_input_type": getattr(config, "document_input_type", None)
        or getattr(config, "document_task_type", None),
        "query_input_type": getattr(config, "query_input_type", None)
        or getattr(config, "query_task_type", None),
    }
    canonical = json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
    descriptor["id"] = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return descriptor
