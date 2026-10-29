import json
from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI

from app.rag.types import RetrievedChunk


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    answer: str
    insufficient_evidence: bool
    cited_chunk_ids: list[str]


class AnswerProvider(Protocol):
    model_name: str | None

    async def answer(self, *, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer: ...


class OpenAIAnswerProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        instructions: str,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.model_name = model
        self.instructions = instructions
        self.client = client or AsyncOpenAI(api_key=api_key)

    async def answer(self, *, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        passages = "\n\n".join(self._format_passage(chunk) for chunk in context)
        response = await self.client.responses.create(
            model=self.model_name,
            instructions=self.instructions,
            input=f"Question:\n{question}\n\nPassages:\n{passages}",
        )
        raw = response.output_text.strip()
        if raw.startswith("```"):
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("answer provider returned invalid JSON") from exc
        return GeneratedAnswer(
            answer=str(payload.get("answer", "")),
            insufficient_evidence=bool(payload.get("insufficient_evidence", False)),
            cited_chunk_ids=[str(item) for item in payload.get("cited_chunk_ids", [])],
        )

    @staticmethod
    def _format_passage(chunk: RetrievedChunk) -> str:
        metadata: list[str] = []
        if chunk.heading_path:
            metadata.append(f"Section: {' > '.join(chunk.heading_path)}")
        if chunk.page_start is not None:
            pages = str(chunk.page_start)
            if chunk.page_end is not None and chunk.page_end != chunk.page_start:
                pages = f"{pages}-{chunk.page_end}"
            metadata.append(f"Pages: {pages}")
        prefix = f"[chunk:{chunk.chunk_id}]"
        if metadata:
            prefix += "\n" + "\n".join(metadata)
        return f"{prefix}\n{chunk.content}"


class StaticAnswerProvider:
    def __init__(self, answer: str = "A grounded test answer.", insufficient: bool = False) -> None:
        self.answer_text = answer
        self.insufficient = insufficient
        self.model_name = "static-test-provider"

    async def answer(self, *, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        del question
        return GeneratedAnswer(
            answer=self.answer_text,
            insufficient_evidence=self.insufficient or not context,
            cited_chunk_ids=[str(chunk.chunk_id) for chunk in context[:1]],
        )
