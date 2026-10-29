from collections.abc import Sequence
from pathlib import Path

from app.rag.chunking import StructureAwareChunker
from app.rag.types import ExtractedBlock, ExtractedDocument


class WordTokenizer:
    def encode(self, text: str) -> list[str]:
        return text.split()

    def decode(self, tokens: Sequence[str]) -> str:
        return " ".join(tokens)


def document(*blocks: ExtractedBlock) -> ExtractedDocument:
    return ExtractedDocument(title="Benefits", source_path=Path("benefits.md"), blocks=list(blocks))


def test_chunker_keeps_heading_context_and_source_metadata() -> None:
    blocks = [
        ExtractedBlock(
            "Eligibility",
            content_type="heading",
            heading_path=["Eligibility"],
            page_start=2,
            page_end=2,
            offset_start=10,
            offset_end=21,
        ),
        ExtractedBlock(
            "Employees qualify after thirty days of work.",
            heading_path=["Eligibility"],
            page_start=2,
            page_end=2,
            offset_start=22,
            offset_end=67,
        ),
    ]
    chunker = StructureAwareChunker(
        target_tokens=20,
        min_tokens=4,
        max_tokens=30,
        overlap_tokens=3,
        tokenizer=WordTokenizer(),  # type: ignore[arg-type]
    )

    chunks = chunker.chunk(document(*blocks))

    assert len(chunks) == 1
    assert chunks[0].heading_path == ["Eligibility"]
    assert chunks[0].page_start == 2
    assert chunks[0].offset_start == 10
    assert "Document: Benefits" in chunks[0].embedding_content
    assert "Section: Eligibility" in chunks[0].embedding_content


def test_chunker_splits_oversized_block_and_respects_maximum() -> None:
    block = ExtractedBlock(" ".join(f"word-{index}" for index in range(40)))
    chunker = StructureAwareChunker(
        target_tokens=10,
        min_tokens=5,
        max_tokens=12,
        overlap_tokens=2,
        tokenizer=WordTokenizer(),  # type: ignore[arg-type]
    )

    chunks = chunker.chunk(document(block))

    assert len(chunks) > 1
    assert all(chunk.token_count <= 12 for chunk in chunks)
    assert any(chunk.metadata["source_block_metadata"] for chunk in chunks)
