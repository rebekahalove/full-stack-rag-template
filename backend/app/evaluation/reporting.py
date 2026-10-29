from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from app.evaluation.engine import trial_error_count
from app.evaluation.models import EvaluationComponent, EvaluationReport, TrialResult

_SENSITIVE_KEYS = {
    "authorization",
    "auth",
    "cookie",
    "credential",
    "credentials",
    "header",
    "headers",
    "password",
    "secret",
    "token",
    "api_key",
}

_SENSITIVE_KEY_SUFFIXES = (
    "_api_key",
    "_access_token",
    "_auth_token",
    "_refresh_token",
    "_authorization",
    "_cookie",
    "_cookies",
    "_credential",
    "_credentials",
    "_header",
    "_headers",
    "_password",
    "_secret",
)

_METRIC_LABELS = {
    "parsing.keyword_recall": "Expected keyword recall",
    "chunking.keyword_coverage": "Keyword coverage",
    "chunking.source_cohesion": "Source cohesion",
    "retrieval.recall": "Source recall",
    "retrieval.precision": "Source precision",
    "retrieval.mrr": "Mean reciprocal rank",
    "generation.answer_keyword_recall": "Answer keyword recall",
    "generation.reference_token_f1": "Reference answer similarity",
    "generation.citation_recall": "Citation recall",
    "generation.citation_precision": "Citation precision",
    "generation.abstention_accuracy": "Abstention accuracy",
    "end_to_end.grounded_answer": "Grounded answer",
}

_COMPONENT_LABELS = {
    EvaluationComponent.PARSING: "Parsing",
    EvaluationComponent.CHUNKING: "Chunking",
    EvaluationComponent.RETRIEVAL: "Retrieval",
    EvaluationComponent.GENERATION: "Generation",
    EvaluationComponent.END_TO_END: "End to end",
}


def _redact_string(value: str) -> str:
    redacted = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", value)
    redacted = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", redacted)
    redacted = re.sub(r"(https?://)[^/@\s:]+:[^/@\s]+@", r"\1[REDACTED]@", redacted)
    return re.sub(
        r"(?i)(api[_-]?key|token|secret|password)=([^&\s]+)",
        r"\1=[REDACTED]",
        redacted,
    )


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(_jsonable(key)): ("[REDACTED]" if _is_sensitive_key(key) else _jsonable(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)


def report_to_json(report: EvaluationReport, *, indent: int = 2) -> str:
    return json.dumps(_jsonable(report), indent=indent, sort_keys=True)


def _table_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _score(value: float) -> str:
    return f"{value * 100:.1f}%"


def _duration(milliseconds: float) -> str:
    if milliseconds < 1000:
        return f"{milliseconds:.0f} ms"
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    return f"{int(seconds // 60)}m {seconds % 60:.0f}s"


def _coverage(result: TrialResult) -> str:
    if result.case_count == 0:
        return "0 / 0"
    percentage = result.successful_case_count / result.case_count
    return f"{result.successful_case_count} / {result.case_count} ({_score(percentage)})"


def _status(result: TrialResult) -> str:
    errors = trial_error_count(result)
    if errors == 0 and result.successful_case_count == result.case_count:
        return "Passed"
    if result.successful_case_count:
        return "Partial"
    return "Failed"


def _metric_label(name: str) -> str:
    if name in _METRIC_LABELS:
        return _METRIC_LABELS[name]
    leaf = name.rsplit(".", maxsplit=1)[-1]
    return leaf.replace("_", " ").capitalize()


def _markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    rendered = [
        "| " + " | ".join(_table_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    rendered.extend("| " + " | ".join(_table_cell(value) for value in row) + " |" for row in rows)
    return rendered


def _error_lines(result: TrialResult) -> list[str]:
    errors = [f"Trial: {message}" for message in result.errors]
    for document in result.documents:
        errors.extend(
            f"Document `{document.document_id}` ({name}): {message}"
            for name, message in document.errors.items()
        )
        for question in document.questions:
            errors.extend(
                f"Question `{question.question_id}` ({name}): {message}"
                for name, message in question.errors.items()
            )
    return errors


def report_to_markdown(report: EvaluationReport) -> str:
    by_trial = {item.result.trial.id: item for item in report.ranking}
    ordered = sorted(report.results, key=lambda item: by_trial[item.trial.id].rank)
    total_cases = sum(result.case_count for result in report.results)
    successful_cases = sum(result.successful_case_count for result in report.results)
    total_errors = sum(trial_error_count(result) for result in report.results)
    top_score = report.ranking[0].objective_score
    top_trials = [
        item.result.trial.id
        for item in report.ranking
        if abs(item.objective_score - top_score) < 1e-12
    ]
    top_label = ", ".join(f"`{trial_id}`" for trial_id in top_trials)

    lines = [
        f"# Evaluation: {report.dataset_name}",
        "",
        "## At a glance",
        "",
        f"- **Top result:** {top_label} at **{_score(top_score)}**",
        f"- **Trials evaluated:** {len(report.results)}",
        f"- **Successful cases:** {successful_cases} / {total_cases}",
        f"- **Errors:** {total_errors}",
        "",
        "## Ranking",
        "",
    ]
    ranking_rows: list[list[object]] = []
    for result in ordered:
        ranked = by_trial[result.trial.id]
        ranking_rows.append(
            [
                str(ranked.rank),
                f"`{result.trial.id}`",
                _score(ranked.objective_score),
                _coverage(result),
                _status(result),
                str(trial_error_count(result)),
            ]
        )
    lines.extend(
        _markdown_table(
            ["Rank", "Trial", "Overall score", "Successful cases", "Status", "Errors"],
            ranking_rows,
        )
    )
    lines.extend(["", "## Trial details", ""])

    for result in ordered:
        ranked = by_trial[result.trial.id]
        lines.extend(
            [
                f"### {ranked.rank}. `{result.trial.id}`",
                "",
            ]
        )
        if result.trial.description:
            lines.extend([result.trial.description, ""])
        lines.extend(
            [
                f"- **Overall score:** {_score(ranked.objective_score)}",
                f"- **Status:** {_status(result)}",
                f"- **Successful cases:** {_coverage(result)}",
                f"- **Duration:** {_duration(result.duration_ms)}",
            ]
        )
        if result.trial.tags:
            lines.append(f"- **Tags:** {', '.join(result.trial.tags)}")

        lines.extend(["", "#### Component scores", ""])
        component_rows = [
            [
                _COMPONENT_LABELS.get(component, component.value.replace("_", " ").title()),
                _score(score),
            ]
            for component, score in sorted(
                result.component_scores.items(), key=lambda item: item[0].value
            )
        ]
        if component_rows:
            lines.extend(_markdown_table(["Pipeline stage", "Score"], component_rows))
        else:
            lines.append("No component scores were produced.")

        lines.extend(["", "#### Detailed metrics", ""])
        metric_rows = [
            [
                _metric_label(name),
                name.split(".", maxsplit=1)[0].replace("_", " ").title(),
                _score(score),
            ]
            for name, score in sorted(result.aggregate_metrics.items())
        ]
        if metric_rows:
            lines.extend(_markdown_table(["Metric", "Component", "Score"], metric_rows))
        else:
            lines.append("No metrics were produced.")

        lines.extend(["", "#### Parameters tested", ""])
        parameter_rows = [
            [name, json.dumps(_jsonable(value), ensure_ascii=False)]
            for name, value in sorted(result.trial.parameters.items())
        ]
        if parameter_rows:
            lines.extend(_markdown_table(["Setting", "Value"], parameter_rows))
        else:
            lines.append("Uses the configured baseline with no trial-specific overrides.")

        errors = _error_lines(result)
        if errors:
            lines.extend(["", "#### Errors", ""])
            lines.extend(f"- {error}" for error in errors)
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "The JSON report contains resolved configuration, per-document and per-question "
            "measurements, timing data, and metric details.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(
    report: EvaluationReport,
    *,
    json_path: str | Path | None = None,
    markdown_path: str | Path | None = None,
) -> None:
    if json_path is not None:
        destination = Path(json_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(report_to_json(report) + "\n", encoding="utf-8")
    if markdown_path is not None:
        destination = Path(markdown_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(report_to_markdown(report), encoding="utf-8")


__all__ = ["report_to_json", "report_to_markdown", "write_report"]
