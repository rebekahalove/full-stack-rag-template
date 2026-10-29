from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

import tiktoken

from app.rag.types import ChunkDraft, ExtractedBlock, ExtractedDocument


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...

    def decode(self, tokens: Sequence[int]) -> str: ...


class TiktokenTokenizer:
    def __init__(self, model: str, fallback_encoding: str) -> None:
        try:
            self._encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            self._encoding = tiktoken.get_encoding(fallback_encoding)

    def encode(self, text: str) -> list[int]:
        return self._encoding.encode(text)

    def decode(self, tokens: Sequence[int]) -> str:
        return self._encoding.decode(list(tokens))


class StructureAwareChunker:
    def __init__(
        self,
        *,
        target_tokens: int,
        min_tokens: int,
        max_tokens: int,
        overlap_tokens: int,
        tokenizer: Tokenizer,
    ) -> None:
        if not 0 <= overlap_tokens < target_tokens:
            raise ValueError("overlap must be non-negative and less than target")
        if not min_tokens <= target_tokens <= max_tokens:
            raise ValueError("chunk sizes must satisfy min <= target <= max")
        self.target_tokens = target_tokens
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.tokenizer = tokenizer

    def chunk(self, document: ExtractedDocument) -> list[ChunkDraft]:
        expanded = self._split_oversized_blocks(document.blocks)
        groups: list[list[ExtractedBlock]] = []
        current: list[ExtractedBlock] = []
        current_tokens = 0

        for block in expanded:
            block_tokens = len(self.tokenizer.encode(block.content))
            heading_changed = bool(current and current[-1].heading_path != block.heading_path)
            would_exceed_target = current_tokens + block_tokens > self.target_tokens
            would_exceed_max = current_tokens + block_tokens > self.max_tokens
            if current and (
                would_exceed_max
                or (would_exceed_target and current_tokens >= self.min_tokens)
                or (heading_changed and current_tokens >= self.min_tokens)
            ):
                groups.append(current)
                current = []
                current_tokens = 0
            current.append(block)
            current_tokens += block_tokens

        if current:
            if groups and current_tokens < self.min_tokens:
                previous_tokens = sum(
                    len(self.tokenizer.encode(block.content)) for block in groups[-1]
                )
                if previous_tokens + current_tokens <= self.max_tokens:
                    groups[-1].extend(current)
                else:
                    groups.append(current)
            else:
                groups.append(current)

        drafts: list[ChunkDraft] = []
        previous_content = ""
        for index, group in enumerate(groups):
            original_content = "\n\n".join(block.content for block in group).strip()
            content = original_content
            overlap_count = 0
            if previous_content and self.overlap_tokens:
                available = max(
                    0,
                    self.max_tokens - len(self.tokenizer.encode(original_content)),
                )
                overlap = self.tokenizer.decode(
                    self.tokenizer.encode(previous_content)[-min(self.overlap_tokens, available) :]
                ).strip()
                if available and overlap and not content.startswith(overlap):
                    content = f"{overlap}\n\n{content}"
                    overlap_count = len(self.tokenizer.encode(overlap))
            heading_path = list(group[0].heading_path)
            context = [f"Document: {document.title}"]
            if heading_path:
                context.append(f"Section: {' > '.join(heading_path)}")
            embedding_content = "\n".join(context) + "\n\n" + content
            pages = [
                page
                for block in group
                for page in (block.page_start, block.page_end)
                if page is not None
            ]
            offsets_start = [
                block.offset_start for block in group if block.offset_start is not None
            ]
            offsets_end = [block.offset_end for block in group if block.offset_end is not None]
            content_types = {block.content_type for block in group}
            metadata = {
                "block_count": len(group),
                "overlap_tokens": overlap_count,
                "source_block_metadata": [block.metadata for block in group if block.metadata],
            }
            drafts.append(
                ChunkDraft(
                    chunk_index=index,
                    content=content,
                    embedding_content=embedding_content,
                    token_count=len(self.tokenizer.encode(content)),
                    heading_path=heading_path,
                    page_start=min(pages) if pages else None,
                    page_end=max(pages) if pages else None,
                    offset_start=min(offsets_start) if offsets_start else None,
                    offset_end=max(offsets_end) if offsets_end else None,
                    content_type=next(iter(content_types)) if len(content_types) == 1 else "mixed",
                    metadata=metadata,
                )
            )
            previous_content = original_content
        return drafts

    def _split_oversized_blocks(self, blocks: Sequence[ExtractedBlock]) -> list[ExtractedBlock]:
        result: list[ExtractedBlock] = []
        stride = self.max_tokens - self.overlap_tokens
        for block in blocks:
            tokens = self.tokenizer.encode(block.content)
            if len(tokens) <= self.max_tokens:
                result.append(block)
                continue
            for part_index, start in enumerate(range(0, len(tokens), stride)):
                part_tokens = tokens[start : start + self.max_tokens]
                if not part_tokens:
                    continue
                metadata = {**block.metadata, "split_part": part_index}
                result.append(
                    replace(
                        block,
                        content=self.tokenizer.decode(part_tokens).strip(),
                        metadata=metadata,
                    )
                )
                if start + self.max_tokens >= len(tokens):
                    break
        return result
