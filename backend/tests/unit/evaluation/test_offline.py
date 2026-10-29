from app.evaluation.models import EvaluationDocument, EvaluationQuestion, ParameterTrial
from app.evaluation.offline import OfflinePipelineConfig, OfflinePipelineRunnerFactory
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.rag.generation import StaticAnswerProvider


def base_config() -> OfflinePipelineConfig:
    return OfflinePipelineConfig(
        parser_pdf_repeated_edge_min_pages=3,
        parser_pdf_repeated_edge_min_occurrences=3,
        parser_pdf_heading_max_characters=100,
        chunk_target_tokens=30,
        chunk_min_tokens=5,
        chunk_max_tokens=50,
        chunk_overlap_tokens=3,
        tokenizer_model="text-embedding-3-small",
        tokenizer_fallback_encoding="cl100k_base",
        embedding_batch_size=2,
        retrieval_candidates_per_method=5,
        retrieval_final_count=2,
        retrieval_rrf_k=60,
        retrieval_near_duplicate_threshold=0.9,
    )


async def test_offline_runner_exercises_pipeline_without_database() -> None:
    factory = OfflinePipelineRunnerFactory(
        base_config=base_config(),
        embedding_provider_factory=lambda trial: DeterministicEmbeddingProvider(dimensions=16),
        answer_provider_factory=lambda trial: StaticAnswerProvider(
            answer="Coverage starts immediately."
        ),
    )
    trial = ParameterTrial(
        id="small-chunks",
        parameters={
            "chunking.target_tokens": 20,
            "chunking.max_tokens": 30,
            "retrieval.final_count": 1,
            "embeddings.provider": "deterministic",
            "generation.provider": "static",
        },
    )
    runner = factory(trial)
    document = EvaluationDocument(
        id="handbook",
        media_type="text/markdown",
        content="# Benefits\n\nCoverage starts immediately after enrollment.",
        questions=(EvaluationQuestion(id="coverage", question="When does coverage start?"),),
    )

    observation = await runner.evaluate_document(document, trial)

    assert observation.parsed_content
    assert observation.chunks
    assert observation.questions["coverage"].retrieved_sources
    assert observation.questions["coverage"].answer == "Coverage starts immediately."
    assert set(observation.stage_timings_ms) == {
        "parsing",
        "chunking",
        "document_embedding",
    }
    assert set(observation.questions["coverage"].stage_timings_ms) == {
        "query_embedding",
        "retrieval",
        "generation",
        "end_to_end",
    }
