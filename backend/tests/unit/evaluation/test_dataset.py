import json
from pathlib import Path

import pytest

from app.evaluation.dataset import DatasetValidationError, load_dataset, load_trials


def test_load_json_dataset_resolves_relative_document_path(tmp_path: Path) -> None:
    document_path = tmp_path / "source.md"
    document_path.write_text("# Benefits\nCoverage begins immediately.", encoding="utf-8")
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "name": "benefits",
                "documents": [
                    {
                        "id": "handbook",
                        "path": "source.md",
                        "media_type": "text/markdown",
                        "questions": [
                            {
                                "id": "coverage",
                                "question": "When does coverage begin?",
                                "reference_answers": ["Coverage begins immediately."],
                                "expected_sources": [
                                    {
                                        "metadata": {"heading_path": ["Benefits"]},
                                        "keywords": ["coverage begins"],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    dataset = load_dataset(dataset_path)

    assert dataset.name == "benefits"
    assert dataset.documents[0].path == document_path.resolve()
    assert dataset.documents[0].questions[0].expected_sources[0].keywords == ("coverage begins",)


def test_load_jsonl_dataset(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    records = [
        {"type": "dataset", "schema_version": "1.0", "name": "inline"},
        {
            "type": "document",
            "id": "doc",
            "content": "A portable inline document.",
            "questions": [{"id": "q", "question": "What is this?"}],
        },
    ]
    path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")

    dataset = load_dataset(path)

    assert dataset.documents[0].content == "A portable inline document."


def test_dataset_rejects_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps({"schema_version": "2.0", "name": "future", "documents": []}),
        encoding="utf-8",
    )

    with pytest.raises(DatasetValidationError, match="unsupported evaluation schema"):
        load_dataset(path)


def test_load_parameter_trials(tmp_path: Path) -> None:
    path = tmp_path / "trials.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "trials": [
                    {
                        "id": "openai-small",
                        "parameters": {
                            "embeddings.provider": "openai",
                            "embeddings.model": "text-embedding-3-small",
                            "generation.provider": "openai",
                            "generation.model": "gpt-4.1-mini",
                            "chunking.target_tokens": 500,
                        },
                        "tags": ["baseline"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    trials = load_trials(path)

    assert trials[0].parameters["generation.model"] == "gpt-4.1-mini"
    assert trials[0].tags == ("baseline",)
