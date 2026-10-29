from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.evaluation.models import (
    SCHEMA_VERSION,
    EvaluationDataset,
    EvaluationDocument,
    EvaluationQuestion,
    ExpectedSource,
    ParameterTrial,
)


class DatasetValidationError(ValueError):
    pass


def _object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DatasetValidationError(f"{location} must be an object")
    return value


def _string(value: Any, location: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise DatasetValidationError(f"{location} must be a string")
    return value


def _string_tuple(value: Any, location: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DatasetValidationError(f"{location} must be an array of strings")
    return tuple(value)


def _metadata(value: Any, location: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _object(value, location)


def _optional_bool(value: Any, location: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise DatasetValidationError(f"{location} must be a boolean")
    return value


def _expected_source(data: Any, location: str) -> ExpectedSource:
    item = _object(data, location)
    try:
        return ExpectedSource(
            source_id=_string(item.get("source_id"), f"{location}.source_id", required=False),
            metadata=_metadata(item.get("metadata"), f"{location}.metadata"),
            keywords=_string_tuple(item.get("keywords"), f"{location}.keywords"),
        )
    except ValueError as exc:
        raise DatasetValidationError(f"{location}: {exc}") from exc


def _question(data: Any, location: str) -> EvaluationQuestion:
    item = _object(data, location)
    sources = item.get("expected_sources", [])
    if not isinstance(sources, list):
        raise DatasetValidationError(f"{location}.expected_sources must be an array")
    try:
        return EvaluationQuestion(
            id=_string(item.get("id"), f"{location}.id") or "",
            question=_string(item.get("question"), f"{location}.question") or "",
            reference_answers=_string_tuple(
                item.get("reference_answers"), f"{location}.reference_answers"
            ),
            expected_answer_keywords=_string_tuple(
                item.get("expected_answer_keywords"),
                f"{location}.expected_answer_keywords",
            ),
            expected_sources=tuple(
                _expected_source(source, f"{location}.expected_sources[{index}]")
                for index, source in enumerate(sources)
            ),
            expected_insufficient_evidence=_optional_bool(
                item.get("expected_insufficient_evidence"),
                f"{location}.expected_insufficient_evidence",
            ),
            metadata=_metadata(item.get("metadata"), f"{location}.metadata"),
        )
    except ValueError as exc:
        raise DatasetValidationError(f"{location}: {exc}") from exc


def _document(data: Any, location: str, base_directory: Path) -> EvaluationDocument:
    item = _object(data, location)
    questions = item.get("questions")
    if not isinstance(questions, list):
        raise DatasetValidationError(f"{location}.questions must be an array")
    path_value = _string(item.get("path"), f"{location}.path", required=False)
    source_path = Path(path_value) if path_value else None
    if source_path is not None and not source_path.is_absolute():
        source_path = (base_directory / source_path).resolve()
    try:
        return EvaluationDocument(
            id=_string(item.get("id"), f"{location}.id") or "",
            path=source_path,
            content=_string(item.get("content"), f"{location}.content", required=False),
            media_type=_string(item.get("media_type"), f"{location}.media_type", required=False),
            expected_keywords=_string_tuple(
                item.get("expected_keywords"), f"{location}.expected_keywords"
            ),
            metadata=_metadata(item.get("metadata"), f"{location}.metadata"),
            questions=tuple(
                _question(question, f"{location}.questions[{index}]")
                for index, question in enumerate(questions)
            ),
        )
    except ValueError as exc:
        raise DatasetValidationError(f"{location}: {exc}") from exc


def _dataset(data: Any, base_directory: Path) -> EvaluationDataset:
    item = _object(data, "dataset")
    version = _string(item.get("schema_version"), "dataset.schema_version")
    if version != SCHEMA_VERSION:
        raise DatasetValidationError(
            f"unsupported evaluation schema {version!r}; expected {SCHEMA_VERSION!r}"
        )
    documents = item.get("documents")
    if not isinstance(documents, list):
        raise DatasetValidationError("dataset.documents must be an array")
    try:
        return EvaluationDataset(
            schema_version=version,
            name=_string(item.get("name"), "dataset.name") or "",
            description=_string(item.get("description"), "dataset.description", required=False),
            metadata=_metadata(item.get("metadata"), "dataset.metadata"),
            documents=tuple(
                _document(document, f"dataset.documents[{index}]", base_directory)
                for index, document in enumerate(documents)
            ),
        )
    except ValueError as exc:
        raise DatasetValidationError(str(exc)) from exc


def load_dataset(path: str | Path) -> EvaluationDataset:
    """Load the versioned JSON or line-oriented JSONL evaluation format."""

    source = Path(path)
    try:
        if source.suffix.lower() == ".jsonl":
            records = [
                json.loads(line)
                for line in source.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if not records:
                raise DatasetValidationError("dataset JSONL file is empty")
            header = _object(records[0], "dataset header")
            if header.get("type") != "dataset":
                raise DatasetValidationError("first JSONL record must have type 'dataset'")
            documents: list[dict[str, Any]] = []
            for index, record in enumerate(records[1:], start=2):
                item = _object(record, f"JSONL line {index}")
                if item.get("type") != "document":
                    raise DatasetValidationError(f"JSONL line {index} must have type 'document'")
                documents.append({key: value for key, value in item.items() if key != "type"})
            data = {key: value for key, value in header.items() if key != "type"} | {
                "documents": documents
            }
        else:
            data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    return _dataset(data, source.parent)


def load_trials(path: str | Path) -> tuple[ParameterTrial, ...]:
    """Load a JSON trial matrix with schema_version and trials fields."""

    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(
            f"invalid trial JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    item = _object(data, "trial matrix")
    version = _string(item.get("schema_version"), "trial matrix.schema_version")
    if version != SCHEMA_VERSION:
        raise DatasetValidationError(
            f"unsupported trial schema {version!r}; expected {SCHEMA_VERSION!r}"
        )
    raw_trials = item.get("trials")
    if not isinstance(raw_trials, list) or not raw_trials:
        raise DatasetValidationError("trial matrix.trials must be a non-empty array")
    trials: list[ParameterTrial] = []
    for index, raw_trial in enumerate(raw_trials):
        location = f"trial matrix.trials[{index}]"
        trial = _object(raw_trial, location)
        parameters = _object(trial.get("parameters"), f"{location}.parameters")
        try:
            trials.append(
                ParameterTrial(
                    id=_string(trial.get("id"), f"{location}.id") or "",
                    description=_string(
                        trial.get("description"), f"{location}.description", required=False
                    ),
                    parameters=parameters,
                    tags=_string_tuple(trial.get("tags"), f"{location}.tags"),
                )
            )
        except ValueError as exc:
            raise DatasetValidationError(f"{location}: {exc}") from exc
    trial_ids = [trial.id for trial in trials]
    if len(trial_ids) != len(set(trial_ids)):
        raise DatasetValidationError("trial matrix has duplicate trial ids")
    return tuple(trials)
