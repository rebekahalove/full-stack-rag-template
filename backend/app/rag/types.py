import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ExtractedBlock:
    content: str
    content_type: str = "text"
    heading_path: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    offset_start: int | None = None
    offset_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedDocument:
    title: str
    source_path: Path
    blocks: list[ExtractedBlock]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChunkDraft:
    chunk_index: int
    content: str
    embedding_content: str
    token_count: int
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    offset_start: int | None
    offset_end: int | None
    content_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    content: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    score: float


@dataclass(frozen=True, slots=True)
class Citation:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    excerpt: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    score: float


@dataclass(frozen=True, slots=True)
class AnswerResult:
    answer: str
    insufficient_evidence: bool
    sources: list[Citation]
