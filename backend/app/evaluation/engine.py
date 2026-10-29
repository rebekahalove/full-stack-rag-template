from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from app.evaluation.interfaces import EvaluationMetric, EvaluationRunnerFactory
from app.evaluation.metrics import default_metrics
from app.evaluation.models import (
    DocumentEvaluationResult,
    EvaluationComponent,
    EvaluationDataset,
    EvaluationReport,
    MetricResult,
    MetricScope,
    ParameterTrial,
    QuestionEvaluationResult,
    RankedTrial,
    TrialResult,
)


def trial_error_count(result: TrialResult) -> int:
    return (
        len(result.errors)
        + sum(len(document.errors) for document in result.documents)
        + sum(
            len(question.errors) for document in result.documents for question in document.questions
        )
    )


def _safe_error(exc: Exception, stage: str) -> str:
    """Persist an actionable error category without copying provider secrets/content."""
    return f"{type(exc).__name__}: {stage} failed"


class EvaluationHarness:
    def __init__(
        self,
        runner_factory: EvaluationRunnerFactory,
        metrics: Sequence[EvaluationMetric] | None = None,
    ) -> None:
        self.runner_factory = runner_factory
        self.metrics = tuple(metrics or default_metrics())
        names = [metric.name for metric in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("evaluation metric names must be unique")

    async def run(
        self,
        dataset: EvaluationDataset,
        trials: Sequence[ParameterTrial],
        *,
        metric_weights: Mapping[str, float] | None = None,
        max_trials: int | None = None,
        max_questions: int | None = None,
    ) -> EvaluationReport:
        if not trials:
            raise ValueError("at least one parameter trial is required")
        if max_trials is not None and len(trials) > max_trials:
            raise ValueError(f"evaluation has {len(trials)} trials; limit is {max_trials}")
        question_count = sum(len(document.questions) for document in dataset.documents) * len(
            trials
        )
        if max_questions is not None and question_count > max_questions:
            raise ValueError(
                f"evaluation has {question_count} trial-questions; limit is {max_questions}"
            )
        weights = dict(metric_weights or {metric.name: 1.0 for metric in self.metrics})
        unknown = set(weights) - {metric.name for metric in self.metrics}
        if unknown:
            raise ValueError(f"weights reference unknown metrics: {', '.join(sorted(unknown))}")
        if any(weight < 0 for weight in weights.values()) or not any(weights.values()):
            raise ValueError("metric weights must be non-negative with at least one positive value")
        results = tuple([await self._run_trial(dataset, trial) for trial in trials])
        ranking = self._rank(results, weights)
        return EvaluationReport(
            dataset_name=dataset.name,
            results=results,
            ranking=ranking,
            metric_weights=weights,
        )

    async def _run_trial(self, dataset: EvaluationDataset, trial: ParameterTrial) -> TrialResult:
        started = time.perf_counter()
        try:
            runner = self.runner_factory(trial)
        except Exception as exc:
            return TrialResult(
                trial=trial,
                documents=(),
                aggregate_metrics={},
                component_scores={},
                duration_ms=(time.perf_counter() - started) * 1000,
                errors=(_safe_error(exc, "runner configuration"),),
                case_count=sum(len(document.questions) for document in dataset.documents),
            )
        document_results: list[DocumentEvaluationResult] = []
        trial_errors: list[str] = []
        all_metrics: list[MetricResult] = []
        document_metrics = [
            metric for metric in self.metrics if metric.scope == MetricScope.DOCUMENT
        ]
        question_metrics = [
            metric for metric in self.metrics if metric.scope == MetricScope.QUESTION
        ]
        for document in dataset.documents:
            try:
                observation = await runner.evaluate_document(document, trial)
            except Exception as exc:
                message = _safe_error(exc, "document pipeline")
                trial_errors.append(f"{document.id}: {message}")
                document_results.append(
                    DocumentEvaluationResult(
                        document_id=document.id,
                        metrics=(),
                        questions=(),
                        errors={"pipeline": message},
                    )
                )
                continue
            measured_document, document_errors = self._measure(
                document_metrics, document, observation, None
            )
            all_metrics.extend(measured_document)
            question_results: list[QuestionEvaluationResult] = []
            for question in document.questions:
                measured_question, question_errors = self._measure(
                    question_metrics, document, observation, question
                )
                all_metrics.extend(measured_question)
                observation_errors = (
                    observation.questions[question.id].errors
                    if question.id in observation.questions
                    else {"runner": "question observation is missing"}
                )
                errors = {**observation_errors, **question_errors}
                question_results.append(
                    QuestionEvaluationResult(
                        question_id=question.id,
                        metrics=tuple(measured_question),
                        stage_timings_ms=(
                            observation.questions[question.id].stage_timings_ms
                            if question.id in observation.questions
                            else {}
                        ),
                        metadata=(
                            observation.questions[question.id].metadata
                            if question.id in observation.questions
                            else {}
                        ),
                        errors=errors,
                    )
                )
            document_results.append(
                DocumentEvaluationResult(
                    document_id=document.id,
                    metrics=tuple(measured_document),
                    questions=tuple(question_results),
                    stage_timings_ms=observation.stage_timings_ms,
                    metadata={
                        "parsed_character_count": len(observation.parsed_content),
                        "chunk_count": len(observation.chunks),
                        **observation.parsed_metadata,
                    },
                    errors={**observation.errors, **document_errors},
                )
            )
        aggregate = self._aggregate_by_name(all_metrics)
        components = self._aggregate_by_component(all_metrics)
        return TrialResult(
            trial=trial,
            documents=tuple(document_results),
            aggregate_metrics=aggregate,
            component_scores=components,
            duration_ms=(time.perf_counter() - started) * 1000,
            errors=tuple(trial_errors),
            resolved_configuration=dict(getattr(runner, "resolved_configuration", {})),
            case_count=sum(len(document.questions) for document in dataset.documents),
            successful_case_count=sum(
                not question.errors
                for document in document_results
                for question in document.questions
            ),
        )

    @staticmethod
    def _measure(metrics, document, observation, question):
        results: list[MetricResult] = []
        errors: dict[str, str] = {}
        for metric in metrics:
            try:
                results.append(metric.evaluate(document, observation, question))
            except Exception as exc:
                errors[metric.name] = _safe_error(exc, f"metric {metric.name}")
        return results, errors

    @staticmethod
    def _aggregate_by_name(metrics: Iterable[MetricResult]) -> dict[str, float]:
        scores: dict[str, list[float]] = defaultdict(list)
        for metric in metrics:
            if metric.applicable:
                scores[metric.name].append(metric.score)
        return {
            name: sum(values) / len(values) for name, values in sorted(scores.items()) if values
        }

    @staticmethod
    def _aggregate_by_component(
        metrics: Iterable[MetricResult],
    ) -> dict[EvaluationComponent, float]:
        scores: dict[EvaluationComponent, list[float]] = defaultdict(list)
        for metric in metrics:
            if metric.applicable:
                scores[metric.component].append(metric.score)
        return {
            component: sum(values) / len(values)
            for component, values in sorted(scores.items(), key=lambda item: item[0].value)
            if values
        }

    @staticmethod
    def _rank(
        results: Sequence[TrialResult], weights: Mapping[str, float]
    ) -> tuple[RankedTrial, ...]:
        scored: list[tuple[TrialResult, float]] = []
        denominator = sum(weight for weight in weights.values() if weight > 0)
        for result in results:
            objective = (
                sum(
                    result.aggregate_metrics.get(name, 0.0) * weight
                    for name, weight in weights.items()
                    if weight > 0
                )
                / denominator
                if denominator
                else 0.0
            )
            scored.append((result, objective))
        scored.sort(
            key=lambda item: (
                trial_error_count(item[0]) > 0,
                item[0].successful_case_count < item[0].case_count,
                -item[1],
                item[0].trial.id,
            )
        )
        return tuple(
            RankedTrial(rank=index, result=result, objective_score=objective)
            for index, (result, objective) in enumerate(scored, start=1)
        )


__all__ = ["EvaluationHarness", "trial_error_count"]
