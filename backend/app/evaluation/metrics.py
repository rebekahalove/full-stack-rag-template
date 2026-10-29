from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.evaluation.models import (
    ActualSource,
    DocumentObservation,
    EvaluationComponent,
    EvaluationDocument,
    EvaluationQuestion,
    ExpectedSource,
    MetricResult,
    MetricScope,
)


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[\w']+", value.casefold()))


def _contains(text: str, keyword: str) -> bool:
    return _normalize(keyword) in _normalize(text)


def _metadata_contains(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if key not in actual:
            return False
        actual_value = actual[key]
        if isinstance(expected_value, dict):
            if not isinstance(actual_value, dict) or not _metadata_contains(
                actual_value, expected_value
            ):
                return False
        elif actual_value != expected_value:
            return False
    return True


def source_matches(expected: ExpectedSource, actual: ActualSource) -> bool:
    if expected.source_id is not None and actual.source_id != expected.source_id:
        return False
    if not _metadata_contains(actual.metadata, expected.metadata):
        return False
    return all(_contains(actual.content, keyword) for keyword in expected.keywords)


def _source_recall(expected: Sequence[ExpectedSource], actual: Sequence[ActualSource]) -> float:
    if not expected:
        return 0.0
    matched = sum(any(source_matches(item, source) for source in actual) for item in expected)
    return matched / len(expected)


def _source_precision(expected: Sequence[ExpectedSource], actual: Sequence[ActualSource]) -> float:
    if not actual:
        return 0.0
    relevant = sum(any(source_matches(item, source) for item in expected) for source in actual)
    return relevant / len(actual)


def _question_observation(question: EvaluationQuestion, observation: DocumentObservation):
    try:
        return observation.questions[question.id]
    except KeyError as exc:
        raise ValueError(f"runner did not return observation for question {question.id!r}") from exc


def _not_applicable(name: str, component: EvaluationComponent, reason: str) -> MetricResult:
    return MetricResult(
        name=name,
        component=component,
        score=0.0,
        applicable=False,
        details={"reason": reason},
    )


def _all_expected_source_keywords(document: EvaluationDocument) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            keyword
            for question in document.questions
            for source in question.expected_sources
            for keyword in source.keywords
        )
    )


@dataclass(frozen=True, slots=True)
class ParsingKeywordRecall:
    name: str = "parsing.keyword_recall"
    scope: MetricScope = MetricScope.DOCUMENT

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del question
        keywords = tuple(
            dict.fromkeys(document.expected_keywords + _all_expected_source_keywords(document))
        )
        if not keywords:
            return _not_applicable(self.name, EvaluationComponent.PARSING, "no expected keywords")
        hits = [keyword for keyword in keywords if _contains(observation.parsed_content, keyword)]
        return MetricResult(
            self.name,
            EvaluationComponent.PARSING,
            len(hits) / len(keywords),
            details={"matched": hits, "expected_count": len(keywords)},
        )


@dataclass(frozen=True, slots=True)
class ChunkKeywordCoverage:
    name: str = "chunking.keyword_coverage"
    scope: MetricScope = MetricScope.DOCUMENT

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del question
        keywords = tuple(
            dict.fromkeys(document.expected_keywords + _all_expected_source_keywords(document))
        )
        if not keywords:
            return _not_applicable(self.name, EvaluationComponent.CHUNKING, "no expected keywords")
        joined = "\n".join(chunk.content for chunk in observation.chunks)
        hits = [keyword for keyword in keywords if _contains(joined, keyword)]
        return MetricResult(
            self.name,
            EvaluationComponent.CHUNKING,
            len(hits) / len(keywords),
            details={"matched": hits, "chunk_count": len(observation.chunks)},
        )


@dataclass(frozen=True, slots=True)
class ChunkSourceCohesion:
    name: str = "chunking.source_cohesion"
    scope: MetricScope = MetricScope.QUESTION

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del document
        if question is None:
            raise ValueError("question metric requires a question")
        if not question.expected_sources:
            return _not_applicable(self.name, EvaluationComponent.CHUNKING, "no expected sources")
        chunks = [
            ActualSource(source_id=chunk.chunk_id, content=chunk.content, metadata=chunk.metadata)
            for chunk in observation.chunks
        ]
        score = _source_recall(question.expected_sources, chunks)
        return MetricResult(
            self.name,
            EvaluationComponent.CHUNKING,
            score,
            details={"expected_source_count": len(question.expected_sources)},
        )


@dataclass(frozen=True, slots=True)
class RetrievalRecall:
    name: str = "retrieval.recall"
    scope: MetricScope = MetricScope.QUESTION

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del document
        if question is None:
            raise ValueError("question metric requires a question")
        if not question.expected_sources:
            return _not_applicable(self.name, EvaluationComponent.RETRIEVAL, "no expected sources")
        actual = _question_observation(question, observation).retrieved_sources
        return MetricResult(
            self.name,
            EvaluationComponent.RETRIEVAL,
            _source_recall(question.expected_sources, actual),
            details={"retrieved_count": len(actual)},
        )


@dataclass(frozen=True, slots=True)
class RetrievalPrecision:
    name: str = "retrieval.precision"
    scope: MetricScope = MetricScope.QUESTION

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del document
        if question is None:
            raise ValueError("question metric requires a question")
        if not question.expected_sources:
            return _not_applicable(self.name, EvaluationComponent.RETRIEVAL, "no expected sources")
        actual = _question_observation(question, observation).retrieved_sources
        return MetricResult(
            self.name,
            EvaluationComponent.RETRIEVAL,
            _source_precision(question.expected_sources, actual),
            details={"retrieved_count": len(actual)},
        )


@dataclass(frozen=True, slots=True)
class RetrievalMeanReciprocalRank:
    name: str = "retrieval.mrr"
    scope: MetricScope = MetricScope.QUESTION

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del document
        if question is None:
            raise ValueError("question metric requires a question")
        if not question.expected_sources:
            return _not_applicable(self.name, EvaluationComponent.RETRIEVAL, "no expected sources")
        actual = _question_observation(question, observation).retrieved_sources
        rank = next(
            (
                index
                for index, source in enumerate(actual, start=1)
                if any(source_matches(item, source) for item in question.expected_sources)
            ),
            None,
        )
        return MetricResult(
            self.name,
            EvaluationComponent.RETRIEVAL,
            1.0 / rank if rank else 0.0,
            details={"first_relevant_rank": rank},
        )


@dataclass(frozen=True, slots=True)
class CitationRecall:
    name: str = "generation.citation_recall"
    scope: MetricScope = MetricScope.QUESTION

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del document
        if question is None:
            raise ValueError("question metric requires a question")
        if not question.expected_sources:
            return _not_applicable(self.name, EvaluationComponent.GENERATION, "no expected sources")
        citations = _question_observation(question, observation).cited_sources
        return MetricResult(
            self.name,
            EvaluationComponent.GENERATION,
            _source_recall(question.expected_sources, citations),
            details={"citation_count": len(citations)},
        )


@dataclass(frozen=True, slots=True)
class CitationPrecision:
    name: str = "generation.citation_precision"
    scope: MetricScope = MetricScope.QUESTION

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del document
        if question is None:
            raise ValueError("question metric requires a question")
        if not question.expected_sources:
            return _not_applicable(self.name, EvaluationComponent.GENERATION, "no expected sources")
        citations = _question_observation(question, observation).cited_sources
        return MetricResult(
            self.name,
            EvaluationComponent.GENERATION,
            _source_precision(question.expected_sources, citations),
            details={"citation_count": len(citations)},
        )


@dataclass(frozen=True, slots=True)
class AnswerKeywordRecall:
    name: str = "generation.answer_keyword_recall"
    scope: MetricScope = MetricScope.QUESTION

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del document
        if question is None:
            raise ValueError("question metric requires a question")
        if not question.expected_answer_keywords:
            return _not_applicable(
                self.name, EvaluationComponent.GENERATION, "no expected answer keywords"
            )
        answer = _question_observation(question, observation).answer
        hits = [
            keyword for keyword in question.expected_answer_keywords if _contains(answer, keyword)
        ]
        return MetricResult(
            self.name,
            EvaluationComponent.GENERATION,
            len(hits) / len(question.expected_answer_keywords),
            details={"matched": hits},
        )


def token_f1(reference: str, answer: str) -> float:
    reference_tokens = Counter(_normalize(reference).split())
    answer_tokens = Counter(_normalize(answer).split())
    if not reference_tokens or not answer_tokens:
        return 1.0 if reference_tokens == answer_tokens else 0.0
    overlap = sum((reference_tokens & answer_tokens).values())
    precision = overlap / sum(answer_tokens.values())
    recall = overlap / sum(reference_tokens.values())
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


@dataclass(frozen=True, slots=True)
class AnswerReferenceTokenF1:
    name: str = "generation.reference_token_f1"
    scope: MetricScope = MetricScope.QUESTION

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del document
        if question is None:
            raise ValueError("question metric requires a question")
        if not question.reference_answers:
            return _not_applicable(
                self.name, EvaluationComponent.GENERATION, "no reference answers"
            )
        answer = _question_observation(question, observation).answer
        scores = [token_f1(reference, answer) for reference in question.reference_answers]
        return MetricResult(
            self.name,
            EvaluationComponent.GENERATION,
            max(scores),
            details={"reference_scores": scores},
        )


@dataclass(frozen=True, slots=True)
class AbstentionAccuracy:
    name: str = "generation.abstention_accuracy"
    scope: MetricScope = MetricScope.QUESTION

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del document
        if question is None:
            raise ValueError("question metric requires a question")
        if question.expected_insufficient_evidence is None:
            return _not_applicable(
                self.name,
                EvaluationComponent.GENERATION,
                "no insufficient-evidence expectation",
            )
        actual = _question_observation(question, observation).insufficient_evidence
        return MetricResult(
            self.name,
            EvaluationComponent.GENERATION,
            float(actual is question.expected_insufficient_evidence),
            details={
                "expected_insufficient_evidence": question.expected_insufficient_evidence,
                "actual_insufficient_evidence": actual,
            },
        )


@dataclass(frozen=True, slots=True)
class EndToEndGroundedAnswer:
    name: str = "end_to_end.grounded_answer"
    scope: MetricScope = MetricScope.QUESTION

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult:
        del document
        if question is None:
            raise ValueError("question metric requires a question")
        actual = _question_observation(question, observation)
        answer_scores: list[float] = []
        if question.reference_answers:
            answer_scores.append(
                max(token_f1(reference, actual.answer) for reference in question.reference_answers)
            )
        if question.expected_answer_keywords:
            answer_scores.append(
                sum(_contains(actual.answer, item) for item in question.expected_answer_keywords)
                / len(question.expected_answer_keywords)
            )
        components = answer_scores[:]
        if question.expected_sources:
            components.append(_source_recall(question.expected_sources, actual.cited_sources))
        if question.expected_insufficient_evidence is not None:
            components.append(
                float(actual.insufficient_evidence is question.expected_insufficient_evidence)
            )
        if not components:
            return _not_applicable(
                self.name, EvaluationComponent.END_TO_END, "no answer or source expectations"
            )
        # Geometric mean penalizes a missing signal without requiring an LLM judge.
        score = math_product(components) ** (1 / len(components))
        return MetricResult(
            self.name,
            EvaluationComponent.END_TO_END,
            score,
            details={"component_scores": components},
        )


def math_product(values: Iterable[float]) -> float:
    result = 1.0
    for value in values:
        result *= value
    return result


def default_metrics():
    return (
        ParsingKeywordRecall(),
        ChunkKeywordCoverage(),
        ChunkSourceCohesion(),
        RetrievalRecall(),
        RetrievalPrecision(),
        RetrievalMeanReciprocalRank(),
        CitationRecall(),
        CitationPrecision(),
        AnswerKeywordRecall(),
        AnswerReferenceTokenF1(),
        AbstentionAccuracy(),
        EndToEndGroundedAnswer(),
    )


__all__ = [
    "AnswerKeywordRecall",
    "AnswerReferenceTokenF1",
    "AbstentionAccuracy",
    "ChunkKeywordCoverage",
    "ChunkSourceCohesion",
    "CitationPrecision",
    "CitationRecall",
    "EndToEndGroundedAnswer",
    "ParsingKeywordRecall",
    "RetrievalMeanReciprocalRank",
    "RetrievalPrecision",
    "RetrievalRecall",
    "default_metrics",
    "source_matches",
    "token_f1",
]
