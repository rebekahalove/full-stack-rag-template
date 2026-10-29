import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question_event import QuestionEvent


class QuestionEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        document_id: uuid.UUID,
        question: str,
        answer: str,
        retrieved_chunk_ids: list[str],
        latency_ms: int,
        model_name: str | None,
        metadata: dict[str, object] | None = None,
    ) -> QuestionEvent:
        event = QuestionEvent(
            document_id=document_id,
            question=question,
            answer=answer,
            retrieved_chunk_ids=retrieved_chunk_ids,
            latency_ms=latency_ms,
            model_name=model_name,
            event_metadata=metadata or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event
