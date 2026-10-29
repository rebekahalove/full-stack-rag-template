import pytest

from app.core.config import get_settings
from app.evaluation.models import ParameterTrial
from app.evaluation_wiring import create_runner


@pytest.fixture
def configured_settings(monkeypatch):
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-embedding-key")
    monkeypatch.setenv("CHAT_API_KEY", "test-chat-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_application_runner_rejects_unknown_trial_parameters(configured_settings) -> None:
    trial = ParameterTrial(
        id="typo",
        parameters={"embeddings.modle": "misspelled-model-key"},
    )

    with pytest.raises(ValueError, match="embeddings.modle"):
        create_runner(trial)


def test_embedding_trial_model_also_drives_default_tokenizer(configured_settings) -> None:
    trial = ParameterTrial(
        id="model",
        parameters={"embeddings.model": "trial-embedding-model"},
    )

    runner = create_runner(trial)

    assert runner.config.tokenizer_model == "trial-embedding-model"
    assert runner.resolved_configuration["embeddings"]["model"] == "trial-embedding-model"
