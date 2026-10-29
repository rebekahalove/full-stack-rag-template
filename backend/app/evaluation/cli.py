from __future__ import annotations

import argparse
import asyncio
import importlib
from collections.abc import Sequence
from typing import Any

from app.core.config import get_settings
from app.evaluation.dataset import load_dataset, load_trials
from app.evaluation.engine import EvaluationHarness, trial_error_count
from app.evaluation.reporting import report_to_markdown, write_report


def _load_attribute(reference: str) -> Any:
    try:
        module_name, attribute_name = reference.split(":", maxsplit=1)
    except ValueError as exc:
        raise ValueError("runner must use module.path:attribute syntax") from exc
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute_name)
    except AttributeError as exc:
        raise ValueError(f"runner attribute {attribute_name!r} was not found") from exc


def _weight(value: str) -> tuple[str, float]:
    try:
        name, raw_weight = value.rsplit("=", maxsplit=1)
        return name, float(raw_weight)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("weights must use metric.name=number") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run modular RAG evaluation trials")
    parser.add_argument("--dataset", required=True, help="Evaluation .json or .jsonl file")
    parser.add_argument("--trials", required=True, help="Parameter trial matrix .json file")
    parser.add_argument(
        "--runner",
        required=True,
        help="Import path for an EvaluationRunnerFactory (module.path:attribute)",
    )
    parser.add_argument("--json-output", help="Write the detailed machine-readable report")
    parser.add_argument("--markdown-output", help="Write the comparison table")
    parser.add_argument("--max-trials", type=int, help="Override EVALUATION_MAX_TRIALS")
    parser.add_argument(
        "--max-questions",
        type=int,
        help="Override EVALUATION_MAX_QUESTIONS (questions multiplied by trials)",
    )
    parser.add_argument("--timeout-seconds", type=float, help="Override EVALUATION_TIMEOUT_SECONDS")
    parser.add_argument(
        "--weight",
        action="append",
        type=_weight,
        default=[],
        metavar="METRIC=WEIGHT",
        help="Override ranking weights; repeat for multiple metrics",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    dataset = load_dataset(args.dataset)
    trials = load_trials(args.trials)
    runner_factory = _load_attribute(args.runner)
    weights = dict(args.weight) or None
    settings = get_settings()
    max_trials = args.max_trials or settings.evaluation_max_trials
    max_questions = args.max_questions or settings.evaluation_max_questions
    timeout_seconds = args.timeout_seconds or settings.evaluation_timeout_seconds
    if min(max_trials, max_questions, timeout_seconds) <= 0:
        raise ValueError("evaluation limits and timeout must be positive")
    async with asyncio.timeout(timeout_seconds):
        report = await EvaluationHarness(runner_factory).run(
            dataset,
            trials,
            metric_weights=weights,
            max_trials=max_trials,
            max_questions=max_questions,
        )
    write_report(
        report,
        json_path=args.json_output,
        markdown_path=args.markdown_output,
    )
    print(report_to_markdown(report))
    return 0 if any(trial_error_count(result) == 0 for result in report.results) else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args))


__all__ = ["build_parser", "main"]
