from app.evaluation.engine import EvaluationHarness
from app.evaluation.models import (
    ActualSource,
    ChunkObservation,
    DocumentObservation,
    EvaluationDataset,
    EvaluationDocument,
    EvaluationQuestion,
    ExpectedSource,
    ParameterTrial,
    QuestionObservation,
    TrialResult,
)
from app.evaluation.reporting import report_to_json, report_to_markdown
from app.evaluation.tuning import expand_parameter_grid


class FakeRunner:
    def __init__(self, relevant: bool) -> None:
        self.relevant = relevant

    async def evaluate_document(self, document, trial):
        del trial
        content = "alpha evidence" if self.relevant else "unrelated text"
        source = ActualSource(content=content, metadata={"section": "one"})
        return DocumentObservation(
            parsed_content=document.content or "",
            chunks=(ChunkObservation(content=document.content or ""),),
            questions={
                "q": QuestionObservation(
                    answer="alpha answer" if self.relevant else "wrong",
                    retrieved_sources=(source,),
                    cited_sources=(source,),
                )
            },
        )


async def test_harness_aggregates_and_ranks_trials() -> None:
    question = EvaluationQuestion(
        id="q",
        question="What is alpha?",
        reference_answers=("alpha answer",),
        expected_answer_keywords=("alpha",),
        expected_sources=(
            ExpectedSource(metadata={"section": "one"}, keywords=("alpha evidence",)),
        ),
    )
    dataset = EvaluationDataset(
        name="ranking",
        documents=(
            EvaluationDocument(
                id="doc",
                content="alpha evidence",
                expected_keywords=("alpha",),
                questions=(question,),
            ),
        ),
    )
    trials = (
        ParameterTrial(id="bad", parameters={"quality": "bad"}),
        ParameterTrial(id="good", parameters={"quality": "good"}),
    )

    report = await EvaluationHarness(
        lambda trial: FakeRunner(trial.parameters["quality"] == "good")
    ).run(dataset, trials)

    assert report.ranking[0].result.trial.id == "good"
    assert report.ranking[0].objective_score > report.ranking[1].objective_score
    assert "retrieval.recall" in report.results[0].aggregate_metrics
    assert report.results[0].documents[0].metadata["chunk_count"] == 1
    json_report = report_to_json(report)
    assert '"dataset_name": "ranking"' in json_report
    assert '"generation.reference_token_f1": 1.0' in json_report
    assert '"generation.reference_token_f1": "[REDACTED]"' not in json_report
    markdown = report_to_markdown(report)
    assert "## At a glance" in markdown
    assert "## Ranking" in markdown
    assert "| 1 | `good` |" in markdown
    assert "### 1. `good`" in markdown
    assert "#### Component scores" in markdown
    assert "#### Detailed metrics" in markdown
    assert "Source recall" in markdown
    assert "Uses the configured baseline" not in markdown


async def test_harness_records_pipeline_failure_and_continues() -> None:
    class BrokenRunner:
        async def evaluate_document(self, document, trial):
            raise RuntimeError(f"cannot process {document.id} in {trial.id}")

    dataset = EvaluationDataset(
        name="errors",
        documents=(
            EvaluationDocument(
                id="doc",
                content="text",
                questions=(EvaluationQuestion(id="q", question="why?"),),
            ),
        ),
    )
    report = await EvaluationHarness(lambda trial: BrokenRunner()).run(
        dataset, (ParameterTrial(id="trial", parameters={}),)
    )

    assert report.results[0].errors
    assert report.results[0].documents[0].errors["pipeline"].startswith("RuntimeError")


def test_expand_parameter_grid_creates_reproducible_trials() -> None:
    trials = expand_parameter_grid(
        {
            "chunking.target_tokens": [400, 600],
            "retrieval.final_count": [4, 8],
        },
        base_parameters={"generation.model": "model-a"},
        id_prefix="sweep",
    )

    assert [trial.id for trial in trials] == [
        "sweep-001",
        "sweep-002",
        "sweep-003",
        "sweep-004",
    ]
    assert all(trial.parameters["generation.model"] == "model-a" for trial in trials)


def test_failed_trial_ranks_after_complete_trial_even_with_higher_score() -> None:
    complete_trial = ParameterTrial(id="complete", parameters={})
    failed_trial = ParameterTrial(id="failed", parameters={})
    complete = TrialResult(
        trial=complete_trial,
        documents=(),
        aggregate_metrics={"quality": 0.5},
        component_scores={},
        duration_ms=1,
        case_count=1,
        successful_case_count=1,
    )
    failed = TrialResult(
        trial=failed_trial,
        documents=(),
        aggregate_metrics={"quality": 1.0},
        component_scores={},
        duration_ms=1,
        errors=("pipeline failed",),
        case_count=1,
    )

    ranking = EvaluationHarness._rank((failed, complete), {"quality": 1.0})

    assert [item.result.trial.id for item in ranking] == ["complete", "failed"]


async def test_harness_enforces_trial_question_budget() -> None:
    dataset = EvaluationDataset(
        name="budget",
        documents=(
            EvaluationDocument(
                id="doc",
                content="text",
                questions=(EvaluationQuestion(id="q", question="why?"),),
            ),
        ),
    )
    trials = (
        ParameterTrial(id="one", parameters={}),
        ParameterTrial(id="two", parameters={}),
    )

    import pytest

    with pytest.raises(ValueError, match="trial-questions"):
        await EvaluationHarness(lambda trial: FakeRunner(True)).run(
            dataset, trials, max_questions=1
        )
