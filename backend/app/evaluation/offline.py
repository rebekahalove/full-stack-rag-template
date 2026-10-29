from __future__ import annotations

import math
import re
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from app.evaluation.interfaces import EvaluationRunner
from app.evaluation.models import (
    ActualSource,
    ChunkObservation,
    DocumentObservation,
    EvaluationDocument,
    ParameterTrial,
    QuestionObservation,
)
from app.rag.chunking import StructureAwareChunker, TiktokenTokenizer
from app.rag.embeddings import EmbeddingProvider
from app.rag.extraction import ExtractionConfig, extract_document
from app.rag.generation import AnswerProvider
from app.rag.retrieval.hybrid import content_fingerprint, is_near_duplicate
from app.rag.types import ChunkDraft, RetrievedChunk


class EmbeddingProviderFactory(Protocol):
    def __call__(self, trial: ParameterTrial) -> EmbeddingProvider: ...


class AnswerProviderFactory(Protocol):
    def __call__(self, trial: ParameterTrial) -> AnswerProvider: ...


OFFLINE_PARAMETER_ALIASES = {
    "parsing.pdf_repeated_edge_min_pages": "parser_pdf_repeated_edge_min_pages",
    "parsing.pdf_repeated_edge_min_occurrences": "parser_pdf_repeated_edge_min_occurrences",
    "parsing.pdf_heading_max_characters": "parser_pdf_heading_max_characters",
    "chunking.target_tokens": "chunk_target_tokens",
    "chunking.min_tokens": "chunk_min_tokens",
    "chunking.max_tokens": "chunk_max_tokens",
    "chunking.overlap_tokens": "chunk_overlap_tokens",
    "chunking.tokenizer_model": "tokenizer_model",
    "chunking.tokenizer_fallback_encoding": "tokenizer_fallback_encoding",
    "embeddings.batch_size": "embedding_batch_size",
    "retrieval.candidates_per_method": "retrieval_candidates_per_method",
    "retrieval.final_count": "retrieval_final_count",
    "retrieval.rrf_k": "retrieval_rrf_k",
    "retrieval.near_duplicate_threshold": "retrieval_near_duplicate_threshold",
}


@dataclass(frozen=True, slots=True)
class OfflinePipelineConfig:
    """Baseline values. Trial parameters selectively override these fields."""

    parser_pdf_repeated_edge_min_pages: int
    parser_pdf_repeated_edge_min_occurrences: int
    parser_pdf_heading_max_characters: int
    chunk_target_tokens: int
    chunk_min_tokens: int
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    tokenizer_model: str
    tokenizer_fallback_encoding: str
    embedding_batch_size: int
    retrieval_candidates_per_method: int
    retrieval_final_count: int
    retrieval_rrf_k: int
    retrieval_near_duplicate_threshold: float

    def __post_init__(self) -> None:
        if not 0 <= self.chunk_overlap_tokens < self.chunk_target_tokens:
            raise ValueError("chunk overlap must be non-negative and below the target")
        if not self.chunk_min_tokens <= self.chunk_target_tokens <= self.chunk_max_tokens:
            raise ValueError("chunk sizes must satisfy min <= target <= max")
        if (
            min(
                self.embedding_batch_size,
                self.retrieval_candidates_per_method,
                self.retrieval_final_count,
                self.retrieval_rrf_k,
            )
            <= 0
        ):
            raise ValueError("embedding and retrieval counts must be positive")
        if not 0 <= self.retrieval_near_duplicate_threshold <= 1:
            raise ValueError("near-duplicate threshold must be between zero and one")

    def with_overrides(self, parameters: Mapping[str, Any]) -> OfflinePipelineConfig:
        updates = {
            field_name: parameters[key]
            for key, field_name in OFFLINE_PARAMETER_ALIASES.items()
            if key in parameters
        }
        return replace(self, **updates)


class OfflinePipelineRunnerFactory:
    """Build a DB-free runner while allowing live or deterministic provider adapters."""

    def __init__(
        self,
        *,
        base_config: OfflinePipelineConfig,
        embedding_provider_factory: EmbeddingProviderFactory,
        answer_provider_factory: AnswerProviderFactory,
    ) -> None:
        self.base_config = base_config
        self.embedding_provider_factory = embedding_provider_factory
        self.answer_provider_factory = answer_provider_factory

    def __call__(self, trial: ParameterTrial) -> EvaluationRunner:
        return OfflinePipelineRunner(
            config=self.base_config.with_overrides(trial.parameters),
            embedding_provider=self.embedding_provider_factory(trial),
            answer_provider=self.answer_provider_factory(trial),
        )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[\w']+", text.casefold()))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("query and chunk embedding dimensions do not match")
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _rrf(rankings: Sequence[Sequence[int]], rank_constant: int) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, index in enumerate(ranking, start=1):
            scores[index] = scores.get(index, 0.0) + 1.0 / (rank_constant + rank)
    maximum = len(rankings) / (rank_constant + 1) if rankings else 1.0
    return sorted(
        ((index, score / maximum) for index, score in scores.items()),
        key=lambda item: (-item[1], item[0]),
    )


def _metadata(document: EvaluationDocument, draft: ChunkDraft) -> dict[str, Any]:
    return {
        **document.metadata,
        **draft.metadata,
        "document_id": document.id,
        "chunk_index": draft.chunk_index,
        "heading_path": draft.heading_path,
        "page_start": draft.page_start,
        "page_end": draft.page_end,
        "content_type": draft.content_type,
    }


class OfflinePipelineRunner:
    """Exercise extract -> chunk -> embed -> retrieve -> generate entirely in memory."""

    def __init__(
        self,
        *,
        config: OfflinePipelineConfig,
        embedding_provider: EmbeddingProvider,
        answer_provider: AnswerProvider,
    ) -> None:
        self.config = config
        self.embedding_provider = embedding_provider
        self.answer_provider = answer_provider
        self.resolved_configuration = {
            "pipeline": asdict(config),
            "embeddings": {
                "provider_class": type(embedding_provider).__name__,
                "model": getattr(embedding_provider, "model", None),
                "dimensions": getattr(embedding_provider, "dimensions", None),
            },
            "generation": {
                "provider_class": type(answer_provider).__name__,
                "model": answer_provider.model_name,
            },
        }

    async def evaluate_document(
        self, document: EvaluationDocument, trial: ParameterTrial
    ) -> DocumentObservation:
        del trial
        stage_timings: dict[str, float] = {}
        extraction_config = ExtractionConfig(
            pdf_repeated_edge_min_pages=self.config.parser_pdf_repeated_edge_min_pages,
            pdf_repeated_edge_min_occurrences=(
                self.config.parser_pdf_repeated_edge_min_occurrences
            ),
            pdf_heading_max_characters=self.config.parser_pdf_heading_max_characters,
        )
        started = time.perf_counter()
        if document.path is not None:
            extracted = extract_document(
                document.path,
                document.media_type or "",
                document.path.name,
                extraction_config,
            )
        else:
            markdown_types = {None, "text/markdown", "text/plain"}
            suffix = ".md" if document.media_type in markdown_types else ".txt"
            with tempfile.TemporaryDirectory(prefix="rag-evaluation-") as directory:
                source = Path(directory) / f"{document.id}{suffix}"
                source.write_text(document.content or "", encoding="utf-8")
                extracted = extract_document(
                    source,
                    document.media_type or "text/markdown",
                    source.name,
                    extraction_config,
                )
        stage_timings["parsing"] = _elapsed_ms(started)

        started = time.perf_counter()
        chunker = StructureAwareChunker(
            target_tokens=self.config.chunk_target_tokens,
            min_tokens=self.config.chunk_min_tokens,
            max_tokens=self.config.chunk_max_tokens,
            overlap_tokens=self.config.chunk_overlap_tokens,
            tokenizer=TiktokenTokenizer(
                self.config.tokenizer_model, self.config.tokenizer_fallback_encoding
            ),
        )
        drafts = chunker.chunk(extracted)
        stage_timings["chunking"] = _elapsed_ms(started)

        started = time.perf_counter()
        embeddings: list[list[float]] = []
        for offset in range(0, len(drafts), self.config.embedding_batch_size):
            batch = drafts[offset : offset + self.config.embedding_batch_size]
            texts = [draft.embedding_content for draft in batch]
            embed_documents = getattr(self.embedding_provider, "embed_documents", None)
            embeddings.extend(
                await embed_documents(texts)
                if embed_documents is not None
                else await self.embedding_provider.embed(texts)
            )
        if len(embeddings) != len(drafts):
            raise ValueError("embedding provider returned an unexpected number of vectors")
        stage_timings["document_embedding"] = _elapsed_ms(started)

        chunk_ids = [
            uuid.uuid5(uuid.NAMESPACE_URL, f"rag-eval:{document.id}:{draft.chunk_index}")
            for draft in drafts
        ]
        question_observations: dict[str, QuestionObservation] = {}
        for question in document.questions:
            question_observations[question.id] = await self._answer_question(
                document, question.question, drafts, embeddings, chunk_ids
            )
        return DocumentObservation(
            parsed_content="\n\n".join(block.content for block in extracted.blocks),
            parsed_metadata=extracted.metadata,
            chunks=tuple(
                ChunkObservation(
                    chunk_id=str(chunk_id),
                    content=draft.content,
                    token_count=draft.token_count,
                    metadata=_metadata(document, draft),
                )
                for chunk_id, draft in zip(chunk_ids, drafts, strict=True)
            ),
            questions=question_observations,
            stage_timings_ms=stage_timings,
        )

    async def _answer_question(
        self,
        document: EvaluationDocument,
        question: str,
        drafts: list[ChunkDraft],
        embeddings: list[list[float]],
        chunk_ids: list[uuid.UUID],
    ) -> QuestionObservation:
        timings: dict[str, float] = {}
        total_started = time.perf_counter()
        started = time.perf_counter()
        embed_query = getattr(self.embedding_provider, "embed_query", None)
        if embed_query is not None:
            query_vector = await embed_query(question)
        else:
            query_vectors = await self.embedding_provider.embed([question])
            if len(query_vectors) != 1:
                raise ValueError("embedding provider did not return one query vector")
            query_vector = query_vectors[0]
        timings["query_embedding"] = _elapsed_ms(started)

        started = time.perf_counter()
        candidates = min(self.config.retrieval_candidates_per_method, len(drafts))
        vector_ranking = sorted(
            range(len(drafts)),
            key=lambda index: (-_cosine(query_vector, embeddings[index]), index),
        )[:candidates]
        query_tokens = _tokens(question)
        keyword_matches = [
            index for index in range(len(drafts)) if query_tokens & _tokens(drafts[index].content)
        ]
        keyword_ranking = sorted(
            keyword_matches,
            key=lambda index: (
                -len(query_tokens & _tokens(drafts[index].content)),
                index,
            ),
        )[:candidates]
        fused = _rrf([vector_ranking, keyword_ranking], self.config.retrieval_rrf_k)
        selected: list[tuple[int, float]] = []
        seen: set[str] = set()
        for index, score in fused:
            fingerprint = content_fingerprint(drafts[index].content)
            if is_near_duplicate(fingerprint, seen, self.config.retrieval_near_duplicate_threshold):
                continue
            seen.add(fingerprint)
            selected.append((index, score))
            if len(selected) >= self.config.retrieval_final_count:
                break
        retrieved = [
            RetrievedChunk(
                chunk_id=chunk_ids[index],
                document_id=uuid.uuid5(uuid.NAMESPACE_URL, f"rag-eval:{document.id}"),
                chunk_index=drafts[index].chunk_index,
                content=drafts[index].content,
                heading_path=drafts[index].heading_path,
                page_start=drafts[index].page_start,
                page_end=drafts[index].page_end,
                score=score,
            )
            for index, score in selected
        ]
        sources_by_id = {
            str(chunk.chunk_id): ActualSource(
                source_id=str(chunk.chunk_id),
                content=chunk.content,
                score=chunk.score,
                metadata=_metadata(document, drafts[chunk.chunk_index]),
            )
            for chunk in retrieved
        }
        timings["retrieval"] = _elapsed_ms(started)

        started = time.perf_counter()
        generated = await self.answer_provider.answer(question=question, context=retrieved)
        timings["generation"] = _elapsed_ms(started)
        timings["end_to_end"] = _elapsed_ms(total_started)
        cited = tuple(
            sources_by_id[source_id]
            for source_id in generated.cited_chunk_ids
            if source_id in sources_by_id
        )
        return QuestionObservation(
            answer=generated.answer,
            retrieved_sources=tuple(sources_by_id.values()),
            cited_sources=cited,
            insufficient_evidence=generated.insufficient_evidence,
            latency_ms=timings["end_to_end"],
            stage_timings_ms=timings,
            metadata={"answer_model": self.answer_provider.model_name},
        )


__all__ = [
    "AnswerProviderFactory",
    "EmbeddingProviderFactory",
    "OfflinePipelineConfig",
    "OfflinePipelineRunner",
    "OfflinePipelineRunnerFactory",
    "OFFLINE_PARAMETER_ALIASES",
]
