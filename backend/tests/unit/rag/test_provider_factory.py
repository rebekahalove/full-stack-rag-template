from pydantic import SecretStr

from app.core.config import PROJECT_ROOT, Settings
from app.rag.provider_factory import (
    build_answer_provider,
    build_embedding_provider,
    embedding_space,
)
from app.rag.providers.openai_compatible import (
    OpenAICompatibleAnswerProvider,
    OpenAICompatibleEmbeddingProvider,
)


def configured_settings(**updates: object) -> Settings:
    baseline = Settings(_env_file=PROJECT_ROOT / ".env.example")
    return Settings.model_validate(
        {
            **baseline.model_dump(),
            "embedding_api_key": SecretStr("test-embedding-key"),
            "chat_api_key": SecretStr("test-chat-key"),
            **updates,
        }
    )


def test_default_provider_factories_build_independent_openai_adapters() -> None:
    settings = configured_settings()

    embeddings = build_embedding_provider(settings)
    chat = build_answer_provider(settings)

    assert isinstance(embeddings, OpenAICompatibleEmbeddingProvider)
    assert isinstance(chat, OpenAICompatibleAnswerProvider)
    assert embeddings.model == "text-embedding-3-small"
    assert chat.model_name == "gpt-4.1-mini"


def test_embedding_space_changes_with_retrieval_critical_settings() -> None:
    baseline = configured_settings()
    changed = configured_settings(embedding_model="another-model")

    first = embedding_space(baseline)
    second = embedding_space(changed)

    assert first["id"] != second["id"]
    assert "api_key" not in first
