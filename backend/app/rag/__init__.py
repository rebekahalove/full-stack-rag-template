"""Public RAG service boundary used by the API layer."""

from app.rag.service import (
    DocumentNotFoundError,
    DocumentNotReadyError,
    IngestionService,
    QuestionAnsweringService,
    RAGConfigurationError,
    RAGService,
)
from app.rag.types import AnswerResult, Citation

__all__ = [
    "AnswerResult",
    "Citation",
    "DocumentNotFoundError",
    "DocumentNotReadyError",
    "IngestionService",
    "QuestionAnsweringService",
    "RAGConfigurationError",
    "RAGService",
]
