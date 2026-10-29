from app.evaluation.models import EvaluationReport, ParameterTrial, RankedTrial, TrialResult
from app.evaluation.reporting import report_to_json, write_report


def report_with_sensitive_trial_value() -> EvaluationReport:
    trial = ParameterTrial(
        id="redaction",
        parameters={"generation.api_key": "must-not-appear", "generation.model": "test"},
        description="Bearer secret-token-value",
    )
    result = TrialResult(
        trial=trial,
        documents=(),
        aggregate_metrics={},
        component_scores={},
        duration_ms=1.0,
    )
    return EvaluationReport(
        dataset_name="test",
        results=(result,),
        ranking=(RankedTrial(rank=1, result=result, objective_score=0.0),),
        metric_weights={},
    )


def test_reports_redact_secrets_and_create_output_directories(tmp_path) -> None:
    report = report_with_sensitive_trial_value()
    json_output = tmp_path / "nested" / "result.json"

    rendered = report_to_json(report)
    write_report(report, json_path=json_output)

    assert "must-not-appear" not in rendered
    assert "secret-token-value" not in rendered
    assert "[REDACTED]" in rendered
    assert json_output.is_file()
