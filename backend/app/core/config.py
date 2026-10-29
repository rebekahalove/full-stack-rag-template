from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime configuration. Deployable defaults live in the root .env.example."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env.example", PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application and API
    app_name: str
    app_version: str
    app_description: str
    backend_cors_origins: Annotated[list[str], NoDecode]
    backend_cors_allow_credentials: bool
    backend_cors_allow_methods: Annotated[list[str], NoDecode]
    backend_cors_allow_headers: Annotated[list[str], NoDecode]

    # Database
    database_url: str
    database_pool_pre_ping: bool
    database_expire_on_commit: bool

    # Uploads
    upload_directory: Path
    max_upload_size_mb: float = Field(gt=0)
    upload_read_size_bytes: int = Field(gt=0)
    upload_pdf_header_bytes: int = Field(gt=0)
    upload_allowed_extensions: Annotated[list[str], NoDecode]

    # Parsing
    parser_version: str
    parser_pdf_repeated_edge_min_pages: int = Field(ge=1)
    parser_pdf_repeated_edge_min_occurrences: int = Field(ge=1)
    parser_pdf_heading_max_characters: int = Field(ge=1)

    # Chunking and tokenization
    tokenizer_fallback_encoding: str
    chunk_target_tokens: int = Field(gt=0)
    chunk_min_tokens: int = Field(gt=0)
    chunk_max_tokens: int = Field(gt=0)
    chunk_overlap_tokens: int = Field(ge=0)

    # Embeddings
    embedding_provider: str
    embedding_api_key: SecretStr | None
    embedding_base_url: str | None
    embedding_model: str
    openai_api_key: SecretStr | None
    anthropic_api_key: SecretStr | None
    google_api_key: SecretStr | None
    gemini_api_key: SecretStr | None
    cohere_api_key: SecretStr | None
    mistral_api_key: SecretStr | None
    voyage_api_key: SecretStr | None
    ollama_api_key: SecretStr | None
    openrouter_api_key: SecretStr | None
    together_api_key: SecretStr | None
    groq_api_key: SecretStr | None
    openai_compatible_api_key: SecretStr | None
    openai_base_url: str
    anthropic_base_url: str
    google_base_url: str
    cohere_base_url: str
    mistral_base_url: str
    voyage_base_url: str
    ollama_base_url: str
    openrouter_base_url: str
    together_base_url: str
    groq_base_url: str
    openai_compatible_base_url: str
    embedding_dimensions: int = Field(gt=0, le=16_000)
    embedding_batch_size: int = Field(gt=0)
    embedding_timeout_seconds: float = Field(gt=0)
    embedding_send_dimensions: bool
    embedding_document_input_type: str
    embedding_query_input_type: str

    # Retrieval
    retrieval_candidates_per_method: int = Field(gt=0)
    retrieval_final_count: int = Field(gt=0)
    retrieval_rrf_k: int = Field(gt=0)
    retrieval_near_duplicate_threshold: float = Field(ge=0, le=1)

    # Answer generation
    chat_provider: str
    chat_api_key: SecretStr | None
    chat_base_url: str | None
    chat_model: str
    chat_timeout_seconds: float = Field(gt=0)
    chat_max_output_tokens: int = Field(gt=0)
    chat_temperature: float = Field(ge=0, le=2)
    chat_send_temperature: bool
    chat_max_tokens_parameter: str
    chat_send_json_response_format: bool
    anthropic_api_version: str
    generation_system_instructions: str
    generation_insufficient_evidence_message: str
    generation_citation_excerpt_characters: int = Field(gt=0)
    generation_fallback_citation_count: int = Field(ge=0)
    question_max_characters: int = Field(gt=0)
    processing_error_max_characters: int = Field(gt=0)

    # Evaluation safeguards
    evaluation_max_trials: int = Field(gt=0)
    evaluation_max_questions: int = Field(gt=0)
    evaluation_timeout_seconds: float = Field(gt=0)

    # Observability
    observability_enabled: bool
    otel_service_name: str
    otel_tracer_name: str
    otel_exporter_otlp_endpoint: str
    otel_batch_export: bool

    @field_validator(
        "backend_cors_origins",
        "backend_cors_allow_methods",
        "backend_cors_allow_headers",
        "upload_allowed_extensions",
        mode="before",
    )
    @classmethod
    def parse_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("upload_allowed_extensions", mode="after")
    @classmethod
    def normalize_extensions(cls, value: list[str]) -> list[str]:
        normalized = [
            item.lower() if item.startswith(".") else f".{item.lower()}" for item in value
        ]
        if not normalized:
            raise ValueError("UPLOAD_ALLOWED_EXTENSIONS must contain at least one extension")
        return normalized

    @field_validator("upload_directory", mode="after")
    @classmethod
    def resolve_upload_directory(cls, value: Path) -> Path:
        """Resolve relative upload paths from the repository root, not the process cwd."""
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @model_validator(mode="after")
    def validate_limits(self) -> "Settings":
        if not 0 <= self.chunk_overlap_tokens < self.chunk_target_tokens:
            raise ValueError("chunk overlap must be non-negative and below the target")
        if not self.chunk_min_tokens <= self.chunk_target_tokens <= self.chunk_max_tokens:
            raise ValueError("chunk sizes must satisfy min <= target <= max")
        if self.retrieval_final_count > self.retrieval_candidates_per_method * 2:
            raise ValueError("final retrieval count exceeds the combined candidate pool")
        if not self.parser_version.strip():
            raise ValueError("PARSER_VERSION must not be empty")
        if self.chat_max_tokens_parameter not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError(
                "CHAT_MAX_TOKENS_PARAMETER must be max_tokens or max_completion_tokens"
            )
        for field_name in ("embedding_provider", "embedding_model", "chat_provider", "chat_model"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name.upper()} must not be empty")
        if not self.otel_service_name.strip() or not self.otel_tracer_name.strip():
            raise ValueError("OpenTelemetry service and tracer names must not be empty")
        if self.observability_enabled and not self.otel_exporter_otlp_endpoint.strip():
            raise ValueError(
                "OTEL_EXPORTER_OTLP_ENDPOINT must not be empty when observability is enabled"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
