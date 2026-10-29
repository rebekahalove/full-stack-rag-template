from __future__ import annotations

from typing import Protocol

from app.evaluation.models import (
    DocumentObservation,
    EvaluationDocument,
    EvaluationQuestion,
    MetricResult,
    MetricScope,
    ParameterTrial,
)


class EvaluationRunner(Protocol):
    """Adapter that runs one document through the system under a parameter trial."""

    async def evaluate_document(
        self, document: EvaluationDocument, trial: ParameterTrial
    ) -> DocumentObservation: ...


class EvaluationRunnerFactory(Protocol):
    def __call__(self, trial: ParameterTrial) -> EvaluationRunner: ...


class EvaluationMetric(Protocol):
    name: str
    scope: MetricScope

    def evaluate(
        self,
        document: EvaluationDocument,
        observation: DocumentObservation,
        question: EvaluationQuestion | None = None,
    ) -> MetricResult: ...
