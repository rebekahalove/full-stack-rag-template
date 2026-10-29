import time
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.observability import NoOpTracer, Tracer
from app.rag.chunking import StructureAwareChunker, TiktokenTokenizer
from app.rag.embeddings import EmbeddingProvider
from app.rag.extraction import ExtractionConfig, extract_document
from app.rag.generation import AnswerProvider
from app.rag.provider_factory import (
    build_answer_provider,
    build_embedding_provider,
    embedding_space_for_provider,
)
from app.rag.retrieval import HybridRetriever
from app.rag.types import AnswerResult, Citation
from app.repositories.chunks import ChunkRepository
from app.repositories.documents import DocumentRepository
from app.repositories.question_events import QuestionEventRepository


class RAGConfigurationError(RuntimeError):
    pass


class DocumentNotFoundError(LookupError):
    pass


class DocumentNotReadyError(RuntimeError):
    pass


def _default_embedding_provider(settings: Settings) -> EmbeddingProvider:
    return build_embedding_provider(settings)


def _default_answer_provider(settings: Settings) -> AnswerProvider:
    return build_answer_provider(settings)


async def _embed_documents(provider: EmbeddingProvider, texts: list[str]) -> list[list[float]]:
    method = getattr(provider, "embed_documents", None)
    if method is not None:
        return await method(texts)
    return await provider.embed(texts)


async def _embed_query(provider: EmbeddingProvider, text: str) -> list[float]:
    method = getattr(provider, "embed_query", None)
    if method is not None:
        return await method(text)
    vectors = await provider.embed([text])
    if len(vectors) != 1:
        raise ValueError("embedding provider did not return one query vector")
    return vectors[0]


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        chunker: StructureAwareChunker | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider
        self.tracer = tracer or NoOpTracer()
        self.chunker = chunker or StructureAwareChunker(
            target_tokens=self.settings.chunk_target_tokens,
            min_tokens=self.settings.chunk_min_tokens,
            max_tokens=self.settings.chunk_max_tokens,
            overlap_tokens=self.settings.chunk_overlap_tokens,
            tokenizer=TiktokenTokenizer(
                self.settings.embedding_model,
                self.settings.tokenizer_fallback_encoding,
            ),
        )
        self.extraction_config = ExtractionConfig(
            pdf_repeated_edge_min_pages=self.settings.parser_pdf_repeated_edge_min_pages,
            pdf_repeated_edge_min_occurrences=(
                self.settings.parser_pdf_repeated_edge_min_occurrences
            ),
            pdf_heading_max_characters=self.settings.parser_pdf_heading_max_characters,
        )
        self.documents = DocumentRepository(session)
        self.chunks = ChunkRepository(session)

    async def ingest(
        self,
        document_id: uuid.UUID,
        path: str | Path,
        media_type: str,
        original_filename: str,
    ) -> Document:
        with self.tracer.start_span(
            "rag.ingest",
            {"document.id": str(document_id), "document.media_type": media_type},
        ) as span:
            document = await self._ingest(document_id, path, media_type, original_filename)
            span.set_attribute("document.status", "ready")
            return document

    async def _ingest(
        self,
        document_id: uuid.UUID,
        path: str | Path,
        media_type: str,
        original_filename: str,
    ) -> Document:
        with self.tracer.start_span(
            "db.document.status",
            {"document.id": str(document_id), "document.status": "processing"},
        ):
            document = await self.documents.get(document_id)
            if document is None:
                raise DocumentNotFoundError(str(document_id))
            await self.documents.update_status(document_id, DocumentStatus.PROCESSING)
            await self.session.commit()
        try:
            with self.tracer.start_span(
                "rag.extract", {"document.media_type": media_type}
            ) as extraction_span:
                extracted = extract_document(
                    Path(path), media_type, original_filename, self.extraction_config
                )
                extraction_span.set_attribute("rag.extracted_block_count", len(extracted.blocks))
            with self.tracer.start_span("rag.chunk") as chunk_span:
                drafts = self.chunker.chunk(extracted)
                chunk_span.set_attribute("rag.chunk_count", len(drafts))
                if not drafts:
                    raise ValueError("document contains no extractable text")
            provider = self.embedding_provider or _default_embedding_provider(self.settings)
            current_space = embedding_space_for_provider(provider)
            embeddings: list[list[float]] = []
            batch_size = self.settings.embedding_batch_size
            for batch_index, start in enumerate(range(0, len(drafts), batch_size)):
                batch = [draft.embedding_content for draft in drafts[start : start + batch_size]]
                with self.tracer.start_span(
                    "rag.embedding.batch",
                    {
                        "rag.batch_index": batch_index,
                        "rag.batch_size": len(batch),
                        "rag.embedding_dimensions": self.settings.embedding_dimensions,
                        "gen_ai.request.model": str(current_space["model"]),
                        "gen_ai.provider.name": str(current_space["provider"]),
                    },
                ):
                    embeddings.extend(await _embed_documents(provider, batch))
            if len(embeddings) != len(drafts):
                raise ValueError("embedding provider returned an unexpected number of vectors")
            if any(len(vector) != self.settings.embedding_dimensions for vector in embeddings):
                raise ValueError("embedding provider returned an unexpected vector dimension")
            values = [
                Chunk(
                    document_id=document_id,
                    chunk_index=draft.chunk_index,
                    content=draft.content,
                    embedding_content=draft.embedding_content,
                    token_count=draft.token_count,
                    heading_path=draft.heading_path,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    offset_start=draft.offset_start,
                    offset_end=draft.offset_end,
                    content_type=draft.content_type,
                    chunk_metadata={
                        **draft.metadata,
                        "embedding_model": current_space["model"],
                        "embedding_provider": current_space["provider"],
                        "embedding_dimensions": self.settings.embedding_dimensions,
                        "embedding_space_id": current_space["id"],
                    },
                    embedding=embedding,
                    embedding_dimensions=self.settings.embedding_dimensions,
                )
                for draft, embedding in zip(drafts, embeddings, strict=True)
            ]
            with self.tracer.start_span(
                "db.chunks.replace",
                {"document.id": str(document_id), "rag.chunk_count": len(values)},
            ):
                await self.chunks.replace_for_document(document_id, values)
                document.document_metadata = {
                    **document.document_metadata,
                    **extracted.metadata,
                    "title": extracted.title,
                    "chunk_count": len(values),
                    "embedding_space": current_space,
                }
                await self.documents.update_status(
                    document_id,
                    DocumentStatus.READY,
                    parser_version=self.settings.parser_version,
                )
                await self.session.commit()
            return document
        except Exception as exc:
            with self.tracer.start_span(
                "db.document.status",
                {"document.id": str(document_id), "document.status": "failed"},
            ):
                await self.session.rollback()
                await self.documents.update_status(
                    document_id,
                    DocumentStatus.FAILED,
                    error_message=str(exc)[: self.settings.processing_error_max_characters],
                    parser_version=self.settings.parser_version,
                )
                await self.session.commit()
            raise


class QuestionAnsweringService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        answer_provider: AnswerProvider | None = None,
        retriever: HybridRetriever | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider
        self.answer_provider = answer_provider
        self.tracer = tracer or NoOpTracer()
        self.documents = DocumentRepository(session)
        self.chunks = ChunkRepository(session)
        self.events = QuestionEventRepository(session)
        self.retriever = retriever or HybridRetriever(
            self.chunks,
            rank_constant=self.settings.retrieval_rrf_k,
            near_duplicate_threshold=self.settings.retrieval_near_duplicate_threshold,
        )

    async def answer(self, document_id: uuid.UUID, question: str) -> AnswerResult:
        with self.tracer.start_span("rag.question", {"document.id": str(document_id)}) as span:
            result = await self._answer(document_id, question)
            span.set_attribute("rag.insufficient_evidence", result.insufficient_evidence)
            span.set_attribute("rag.source_count", len(result.sources))
            return result

    async def _answer(self, document_id: uuid.UUID, question: str) -> AnswerResult:
        started = time.perf_counter()
        document = await self.documents.get(document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        if document.status != DocumentStatus.READY:
            raise DocumentNotReadyError(f"document status is {document.status.value}")
        provider = self.embedding_provider or _default_embedding_provider(self.settings)
        stored_space = document.document_metadata.get("embedding_space")
        current_space = embedding_space_for_provider(provider)
        if not isinstance(stored_space, dict):
            first_chunk = await self.chunks.first_metadata(document_id)
            is_legacy_openai = (
                self.embedding_provider is None
                and self.settings.embedding_provider.strip().casefold().replace("-", "_")
                == "openai"
                and self.settings.embedding_dimensions == 1536
                and self.settings.embedding_base_url in (None, "")
                and self.settings.openai_base_url.rstrip("/") == "https://api.openai.com/v1"
                and isinstance(first_chunk, dict)
                and first_chunk.get("embedding_model") == self.settings.embedding_model
            )
            if not is_legacy_openai:
                raise RAGConfigurationError(
                    "document embedding identity is missing; re-upload it before asking questions"
                )
            document.document_metadata = {
                **document.document_metadata,
                "embedding_space": current_space,
            }
            await self.session.commit()
            stored_space = current_space
        if stored_space.get("id") != current_space["id"]:
            raise RAGConfigurationError(
                "document embeddings do not match the selected embedding provider/model; "
                "re-upload it to rebuild its vectors"
            )
        with self.tracer.start_span(
            "rag.embedding.query",
            {
                "rag.batch_size": 1,
                "rag.embedding_dimensions": self.settings.embedding_dimensions,
                "gen_ai.request.model": str(current_space["model"]),
                "gen_ai.provider.name": str(current_space["provider"]),
            },
        ):
            query_vector = await _embed_query(provider, question)
        if len(query_vector) != self.settings.embedding_dimensions:
            raise ValueError("embedding provider returned an unexpected query vector dimension")
        with self.tracer.start_span(
            "rag.retrieve",
            {
                "document.id": str(document_id),
                "rag.candidates_per_method": self.settings.retrieval_candidates_per_method,
                "rag.requested_result_count": self.settings.retrieval_final_count,
            },
        ) as retrieval_span:
            retrieved = await self.retriever.retrieve(
                document_id=document_id,
                question=question,
                query_embedding=query_vector,
                candidates_per_method=self.settings.retrieval_candidates_per_method,
                final_count=self.settings.retrieval_final_count,
            )
            retrieval_span.set_attribute("rag.result_count", len(retrieved))
        if not retrieved:
            answer = self.settings.generation_insufficient_evidence_message
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            with self.tracer.start_span(
                "db.question_event.create",
                {"document.id": str(document_id), "rag.result_count": 0},
            ):
                await self.events.create(
                    document_id=document_id,
                    question=question,
                    answer=answer,
                    retrieved_chunk_ids=[],
                    latency_ms=elapsed_ms,
                    model_name=None,
                    metadata={"insufficient_evidence": True},
                )
                await self.session.commit()
            return AnswerResult(
                answer=answer,
                insufficient_evidence=True,
                sources=[],
            )
        answer_provider = self.answer_provider or _default_answer_provider(self.settings)
        with self.tracer.start_span(
            "rag.generate",
            {
                "gen_ai.request.model": answer_provider.model_name,
                "rag.context_count": len(retrieved),
            },
        ) as generation_span:
            generated = await answer_provider.answer(question=question, context=retrieved)
            generation_span.set_attribute(
                "rag.insufficient_evidence", generated.insufficient_evidence
            )
            generation_span.set_attribute("rag.cited_source_count", len(generated.cited_chunk_ids))
        allowed_ids = {str(chunk.chunk_id) for chunk in retrieved}
        cited_ids = {item for item in generated.cited_chunk_ids if item in allowed_ids}
        cited_chunks = [chunk for chunk in retrieved if str(chunk.chunk_id) in cited_ids]
        if not cited_chunks and not generated.insufficient_evidence:
            cited_chunks = retrieved[: self.settings.generation_fallback_citation_count]
        citations = [
            Citation(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_name=document.original_filename,
                excerpt=chunk.content[: self.settings.generation_citation_excerpt_characters],
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                score=chunk.score,
            )
            for chunk in cited_chunks
        ]
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        with self.tracer.start_span(
            "db.question_event.create",
            {
                "document.id": str(document_id),
                "rag.result_count": len(retrieved),
            },
        ):
            await self.events.create(
                document_id=document_id,
                question=question,
                answer=generated.answer,
                retrieved_chunk_ids=[str(chunk.chunk_id) for chunk in retrieved],
                latency_ms=elapsed_ms,
                model_name=answer_provider.model_name,
                metadata={"insufficient_evidence": generated.insufficient_evidence},
            )
            await self.session.commit()
        return AnswerResult(
            answer=generated.answer,
            insufficient_evidence=generated.insufficient_evidence,
            sources=citations,
        )


class RAGService:
    """Convenience facade when callers prefer one RAG dependency."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        answer_provider: AnswerProvider | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        tracer = tracer or NoOpTracer()
        self.ingestion = IngestionService(
            session, settings, embedding_provider=embedding_provider, tracer=tracer
        )
        self.questions = QuestionAnsweringService(
            session,
            settings,
            embedding_provider=embedding_provider,
            answer_provider=answer_provider,
            tracer=tracer,
        )

    async def ingest(
        self,
        document_id: uuid.UUID,
        path: str | Path,
        media_type: str,
        original_filename: str,
    ) -> Document:
        return await self.ingestion.ingest(document_id, path, media_type, original_filename)

    async def answer(self, document_id: uuid.UUID, question: str) -> AnswerResult:
        return await self.questions.answer(document_id, question)
