from app.evaluation.metrics import (
    AbstentionAccuracy,
    AnswerReferenceTokenF1,
    CitationPrecision,
    CitationRecall,
    RetrievalMeanReciprocalRank,
    RetrievalPrecision,
    RetrievalRecall,
    token_f1,
)
from app.evaluation.models import (
    ActualSource,
    ChunkObservation,
    DocumentObservation,
    EvaluationDocument,
    EvaluationQuestion,
    ExpectedSource,
    QuestionObservation,
)


def make_example():
    question = EvaluationQuestion(
        id="q1",
        question="When does coverage begin?",
        reference_answers=("Coverage begins on the first day.",),
        expected_answer_keywords=("first day",),
        expected_sources=(
            ExpectedSource(metadata={"section": "benefits"}, keywords=("first day",)),
        ),
    )
    document = EvaluationDocument(
        id="doc",
        content="Coverage begins on the first day.",
        questions=(question,),
    )
    irrelevant = ActualSource(
        source_id="irrelevant",
        content="Vacation policy.",
        metadata={"section": "leave"},
    )
    relevant = ActualSource(
        source_id="relevant",
        content="Coverage begins on the first day.",
        metadata={"section": "benefits"},
    )
    observation = DocumentObservation(
        parsed_content=document.content or "",
        chunks=(ChunkObservation(content=document.content or ""),),
        questions={
            "q1": QuestionObservation(
                answer="Coverage begins on the first day.",
                retrieved_sources=(irrelevant, relevant),
                cited_sources=(relevant,),
            )
        },
    )
    return document, question, observation


def test_retrieval_metrics_are_deterministic() -> None:
    document, question, observation = make_example()

    recall = RetrievalRecall().evaluate(document, observation, question)
    precision = RetrievalPrecision().evaluate(document, observation, question)
    mrr = RetrievalMeanReciprocalRank().evaluate(document, observation, question)

    assert recall.score == 1.0
    assert precision.score == 0.5
    assert mrr.score == 0.5


def test_citation_and_reference_answer_metrics() -> None:
    document, question, observation = make_example()

    assert CitationRecall().evaluate(document, observation, question).score == 1.0
    assert CitationPrecision().evaluate(document, observation, question).score == 1.0
    assert AnswerReferenceTokenF1().evaluate(document, observation, question).score == 1.0
    assert token_f1("alpha beta", "alpha gamma") == 0.5


def test_metric_without_ground_truth_is_not_applicable() -> None:
    question = EvaluationQuestion(id="q", question="Anything?")
    document = EvaluationDocument(id="doc", content="text", questions=(question,))
    observation = DocumentObservation(
        parsed_content="text",
        chunks=(),
        questions={"q": QuestionObservation(answer="answer")},
    )

    result = RetrievalRecall().evaluate(document, observation, question)

    assert result.applicable is False


def test_abstention_accuracy_scores_expected_insufficient_evidence() -> None:
    question = EvaluationQuestion(
        id="q",
        question="What is the executive's phone number?",
        expected_insufficient_evidence=True,
    )
    document = EvaluationDocument(id="doc", content="No phone number.", questions=(question,))
    observation = DocumentObservation(
        parsed_content="No phone number.",
        chunks=(),
        questions={
            "q": QuestionObservation(
                answer="The document does not provide that information.",
                insufficient_evidence=True,
            )
        },
    )

    assert AbstentionAccuracy().evaluate(document, observation, question).score == 1.0
