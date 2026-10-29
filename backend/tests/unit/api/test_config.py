import pytest
from pydantic import ValidationError

from app.core.config import PROJECT_ROOT, Settings


def test_example_environment_covers_every_backend_setting() -> None:
    keys = {
        line.split("=", 1)[0]
        for line in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }

    assert {name.upper() for name in Settings.model_fields}.issubset(keys)


def test_cors_origins_accept_comma_separated_environment_value(monkeypatch) -> None:
    monkeypatch.setenv(
        "BACKEND_CORS_ORIGINS",
        "http://localhost:5173, http://127.0.0.1:5173",
    )

    settings = Settings(_env_file=PROJECT_ROOT / ".env.example")

    assert settings.backend_cors_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_embedding_dimensions_respect_pgvector_storage_limit() -> None:
    settings = Settings(_env_file=PROJECT_ROOT / ".env.example", embedding_dimensions=16_000)

    assert settings.embedding_dimensions == 16_000

    with pytest.raises(ValidationError, match="less than or equal to 16000"):
        Settings(_env_file=PROJECT_ROOT / ".env.example", embedding_dimensions=16_001)
