import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    chunk: Chunk
    score: float


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_for_document(
        self, document_id: uuid.UUID, chunks: Iterable[Chunk]
    ) -> list[Chunk]:
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        values = list(chunks)
        self.session.add_all(values)
        await self.session.flush()
        return values

    async def vector_candidates(
        self,
        *,
        document_id: uuid.UUID,
        query_embedding: list[float],
        limit: int,
    ) -> list[ScoredChunk]:
        distance = Chunk.embedding.cosine_distance(query_embedding)
        statement = (
            select(Chunk, distance.label("distance"))
            .where(
                Chunk.document_id == document_id,
                Chunk.embedding_dimensions == len(query_embedding),
            )
            .order_by(distance)
            .limit(limit)
        )
        rows = (await self.session.execute(statement)).all()
        return [
            ScoredChunk(chunk=chunk, score=max(0.0, 1.0 - float(distance_value)))
            for chunk, distance_value in rows
        ]

    async def keyword_candidates(
        self, *, document_id: uuid.UUID, query: str, limit: int
    ) -> list[ScoredChunk]:
        ts_query = func.websearch_to_tsquery("english", query)
        rank = func.ts_rank_cd(Chunk.text_search, ts_query)
        statement = (
            select(Chunk, rank.label("rank"))
            .where(Chunk.document_id == document_id, Chunk.text_search.op("@@")(ts_query))
            .order_by(rank.desc(), Chunk.chunk_index)
            .limit(limit)
        )
        rows = (await self.session.execute(statement)).all()
        return [ScoredChunk(chunk=chunk, score=float(rank_value)) for chunk, rank_value in rows]

    async def adjacent(
        self, *, document_id: uuid.UUID, chunk_index: int, window: int
    ) -> list[Chunk]:
        statement = (
            select(Chunk)
            .where(
                Chunk.document_id == document_id,
                Chunk.chunk_index.between(chunk_index - window, chunk_index + window),
            )
            .order_by(Chunk.chunk_index)
        )
        return list(await self.session.scalars(statement))

    async def first_metadata(self, document_id: uuid.UUID) -> dict | None:
        statement = (
            select(Chunk.chunk_metadata)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
            .limit(1)
        )
        value = await self.session.scalar(statement)
        return value if isinstance(value, dict) else None
