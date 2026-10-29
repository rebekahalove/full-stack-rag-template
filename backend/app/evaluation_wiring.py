from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.evaluation.models import ParameterTrial
from app.evaluation.offline import (
    OFFLINE_PARAMETER_ALIASES,
    OfflinePipelineConfig,
    OfflinePipelineRunner,
    OfflinePipelineRunnerFactory,
)
from app.rag.provider_factory import build_answer_provider, build_embedding_provider

APPLICATION_SETTING_ALIASES = {
    "embeddings.provider": "embedding_provider",
    "embeddings.model": "embedding_model",
    "embeddings.dimensions": "embedding_dimensions",
    "embeddings.base_url": "embedding_base_url",
    "embeddings.batch_size": "embedding_batch_size",
    "embeddings.timeout_seconds": "embedding_timeout_seconds",
    "embeddings.send_dimensions": "embedding_send_dimensions",
    "embeddings.document_input_type": "embedding_document_input_type",
    "embeddings.query_input_type": "embedding_query_input_type",
    "generation.provider": "chat_provider",
    "generation.model": "chat_model",
    "generation.base_url": "chat_base_url",
    "generation.timeout_seconds": "chat_timeout_seconds",
    "generation.max_output_tokens": "chat_max_output_tokens",
    "generation.temperature": "chat_temperature",
    "generation.send_temperature": "chat_send_temperature",
    "generation.max_tokens_parameter": "chat_max_tokens_parameter",
    "generation.send_json_response_format": "chat_send_json_response_format",
    "generation.system_instructions": "generation_system_instructions",
}


def _trial_settings(settings: Settings, trial: ParameterTrial) -> Settings:
    updates: dict[str, Any] = {
        setting_name: trial.parameters[key]
        for key, setting_name in APPLICATION_SETTING_ALIASES.items()
        if key in trial.parameters
    }
    return Settings.model_validate({**settings.model_dump(), **updates})


def _base_config(settings: Settings) -> OfflinePipelineConfig:
    return OfflinePipelineConfig(
        parser_pdf_repeated_edge_min_pages=settings.parser_pdf_repeated_edge_min_pages,
        parser_pdf_repeated_edge_min_occurrences=(
            settings.parser_pdf_repeated_edge_min_occurrences
        ),
        parser_pdf_heading_max_characters=settings.parser_pdf_heading_max_characters,
        chunk_target_tokens=settings.chunk_target_tokens,
        chunk_min_tokens=settings.chunk_min_tokens,
        chunk_max_tokens=settings.chunk_max_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
        tokenizer_model=settings.embedding_model,
        tokenizer_fallback_encoding=settings.tokenizer_fallback_encoding,
        embedding_batch_size=settings.embedding_batch_size,
        retrieval_candidates_per_method=settings.retrieval_candidates_per_method,
        retrieval_final_count=settings.retrieval_final_count,
        retrieval_rrf_k=settings.retrieval_rrf_k,
        retrieval_near_duplicate_threshold=settings.retrieval_near_duplicate_threshold,
    )


def create_runner(trial: ParameterTrial) -> OfflinePipelineRunner:
    """Build a DB-free evaluator using env credentials and trial-selected parameters."""
    baseline = get_settings()
    unknown = (
        set(trial.parameters) - set(APPLICATION_SETTING_ALIASES) - set(OFFLINE_PARAMETER_ALIASES)
    )
    if unknown:
        raise ValueError(f"unsupported trial parameters: {', '.join(sorted(unknown))}")
    selected = _trial_settings(baseline, trial)
    factory = OfflinePipelineRunnerFactory(
        base_config=_base_config(selected),
        embedding_provider_factory=lambda _trial: build_embedding_provider(selected),
        answer_provider_factory=lambda _trial: build_answer_provider(selected),
    )
    return factory(trial)


__all__ = ["create_runner"]
