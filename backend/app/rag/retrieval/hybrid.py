import re
import uuid
from collections.abc import Sequence

from app.rag.types import RetrievedChunk
from app.repositories.chunks import ChunkRepository, ScoredChunk


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[ScoredChunk]], *, rank_constant: int
) -> list[tuple[ScoredChunk, float]]:
    by_id: dict[uuid.UUID, ScoredChunk] = {}
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            by_id[item.chunk.id] = item
            scores[item.chunk.id] = scores.get(item.chunk.id, 0.0) + 1.0 / (rank_constant + rank)
    maximum = len(rankings) / (rank_constant + 1) if rankings else 1.0
    return sorted(
        ((by_id[chunk_id], score / maximum) for chunk_id, score in scores.items()),
        key=lambda item: (-item[1], item[0].chunk.chunk_index),
    )


def content_fingerprint(content: str) -> str:
    return re.sub(r"\W+", " ", content.casefold()).strip()


def is_near_duplicate(fingerprint: str, seen: set[str], threshold: float) -> bool:
    words = set(fingerprint.split())
    if not words:
        return True
    for existing in seen:
        existing_words = set(existing.split())
        union = words | existing_words
        if union and len(words & existing_words) / len(union) >= threshold:
            return True
    return False


class HybridRetriever:
    def __init__(
        self,
        repository: ChunkRepository,
        *,
        rank_constant: int,
        near_duplicate_threshold: float,
    ) -> None:
        self.repository = repository
        self.rank_constant = rank_constant
        self.near_duplicate_threshold = near_duplicate_threshold

    async def retrieve(
        self,
        *,
        document_id: uuid.UUID,
        question: str,
        query_embedding: list[float],
        candidates_per_method: int,
        final_count: int,
    ) -> list[RetrievedChunk]:
        vector = await self.repository.vector_candidates(
            document_id=document_id,
            query_embedding=query_embedding,
            limit=candidates_per_method,
        )
        keyword = await self.repository.keyword_candidates(
            document_id=document_id,
            query=question,
            limit=candidates_per_method,
        )
        fused = reciprocal_rank_fusion([vector, keyword], rank_constant=self.rank_constant)
        results: list[RetrievedChunk] = []
        seen: set[str] = set()
        for item, score in fused:
            fingerprint = content_fingerprint(item.chunk.content)
            if is_near_duplicate(fingerprint, seen, self.near_duplicate_threshold):
                continue
            seen.add(fingerprint)
            results.append(
                RetrievedChunk(
                    chunk_id=item.chunk.id,
                    document_id=item.chunk.document_id,
                    chunk_index=item.chunk.chunk_index,
                    content=item.chunk.content,
                    heading_path=list(item.chunk.heading_path),
                    page_start=item.chunk.page_start,
                    page_end=item.chunk.page_end,
                    score=score,
                )
            )
            if len(results) >= final_count:
                break
        return results
