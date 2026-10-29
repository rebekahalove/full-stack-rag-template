import uuid

from app.models.chunk import Chunk
from app.rag.retrieval import reciprocal_rank_fusion
from app.repositories.chunks import ScoredChunk


def make_chunk(index: int) -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=index,
        content=f"chunk {index}",
        embedding_content=f"chunk {index}",
        token_count=2,
        heading_path=[],
        content_type="text",
        chunk_metadata={},
        embedding=[0.0] * 1536,
        embedding_dimensions=1536,
    )


def test_reciprocal_rank_fusion_rewards_results_from_both_methods() -> None:
    shared = ScoredChunk(make_chunk(1), 0.8)
    vector_only = ScoredChunk(make_chunk(2), 0.9)
    keyword_only = ScoredChunk(make_chunk(3), 0.9)

    fused = reciprocal_rank_fusion(
        [[vector_only, shared], [keyword_only, shared]], rank_constant=10
    )

    assert fused[0][0].chunk.id == shared.chunk.id
    assert 0.0 <= fused[0][1] <= 1.0
    assert len(fused) == 3
