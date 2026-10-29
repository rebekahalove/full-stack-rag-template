from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"


class EvaluationComponent(StrEnum):
    PARSING = "parsing"
    CHUNKING = "chunking"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"
    END_TO_END = "end_to_end"


class MetricScope(StrEnum):
    DOCUMENT = "document"
    QUESTION = "question"


@dataclass(frozen=True, slots=True)
class ExpectedSource:
    """A source expectation matched by metadata and/or required content keywords."""

    source_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id and not self.metadata and not self.keywords:
            raise ValueError("an expected source needs an id, metadata, or keywords")
        if self.source_id and not self.metadata and not self.keywords:
            raise ValueError(
                "source_id cannot be the only evidence predicate because chunk IDs vary by trial"
            )


@dataclass(frozen=True, slots=True)
class EvaluationQuestion:
    id: str
    question: str
    reference_answers: tuple[str, ...] = ()
    expected_answer_keywords: tuple[str, ...] = ()
    expected_sources: tuple[ExpectedSource, ...] = ()
    expected_insufficient_evidence: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("question id cannot be blank")
        if not self.question.strip():
            raise ValueError(f"question {self.id!r} cannot be blank")


@dataclass(frozen=True, slots=True)
class EvaluationDocument:
    id: str
    questions: tuple[EvaluationQuestion, ...]
    path: Path | None = None
    content: str | None = None
    media_type: str | None = None
    expected_keywords: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("document id cannot be blank")
        if self.path is None and self.content is None:
            raise ValueError(f"document {self.id!r} needs path or content")
        if not self.questions:
            raise ValueError(f"document {self.id!r} needs at least one question")
        question_ids = [question.id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError(f"document {self.id!r} has duplicate question ids")


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    name: str
    documents: tuple[EvaluationDocument, ...]
    schema_version: str = SCHEMA_VERSION
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                "unsupported evaluation schema "
                f"{self.schema_version!r}; expected {SCHEMA_VERSION!r}"
            )
        if not self.name.strip():
            raise ValueError("dataset name cannot be blank")
        if not self.documents:
            raise ValueError("dataset needs at least one document")
        document_ids = [document.id for document in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("dataset has duplicate document ids")


@dataclass(frozen=True, slots=True)
class ParameterTrial:
    """One complete configuration/model combination to evaluate."""

    id: str
    parameters: dict[str, Any]
    description: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("trial id cannot be blank")


@dataclass(frozen=True, slots=True)
class ActualSource:
    source_id: str | None = None
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float | None = None


@dataclass(frozen=True, slots=True)
class ChunkObservation:
    content: str
    chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    token_count: int | None = None


@dataclass(frozen=True, slots=True)
class QuestionObservation:
    answer: str
    retrieved_sources: tuple[ActualSource, ...] = ()
    cited_sources: tuple[ActualSource, ...] = ()
    insufficient_evidence: bool = False
    latency_ms: float | None = None
    stage_timings_ms: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentObservation:
    parsed_content: str
    chunks: tuple[ChunkObservation, ...]
    questions: dict[str, QuestionObservation]
    parsed_metadata: dict[str, Any] = field(default_factory=dict)
    stage_timings_ms: dict[str, float] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MetricResult:
    name: str
    component: EvaluationComponent
    score: float
    applicable: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"metric {self.name!r} score must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class QuestionEvaluationResult:
    question_id: str
    metrics: tuple[MetricResult, ...]
    stage_timings_ms: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentEvaluationResult:
    document_id: str
    metrics: tuple[MetricResult, ...]
    questions: tuple[QuestionEvaluationResult, ...]
    stage_timings_ms: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TrialResult:
    trial: ParameterTrial
    documents: tuple[DocumentEvaluationResult, ...]
    aggregate_metrics: dict[str, float]
    component_scores: dict[EvaluationComponent, float]
    duration_ms: float
    errors: tuple[str, ...] = ()
    resolved_configuration: dict[str, Any] = field(default_factory=dict)
    case_count: int = 0
    successful_case_count: int = 0


@dataclass(frozen=True, slots=True)
class RankedTrial:
    rank: int
    result: TrialResult
    objective_score: float


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    dataset_name: str
    results: tuple[TrialResult, ...]
    ranking: tuple[RankedTrial, ...]
    metric_weights: dict[str, float]
