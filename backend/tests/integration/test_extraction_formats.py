from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.extraction import ExtractionConfig, extract_document

from .conftest import minimal_docx_bytes, minimal_pdf_bytes

EXTRACTION_CONFIG = ExtractionConfig(
    pdf_repeated_edge_min_pages=3,
    pdf_repeated_edge_min_occurrences=3,
    pdf_heading_max_characters=100,
)


@pytest.mark.parametrize(
    ("filename", "media_type", "content", "expected_text"),
    [
        (
            "benefits.md",
            "text/markdown",
            b"# Benefits\n\n## Eligibility\n\nCoverage begins after enrollment.\n",
            "Coverage begins after enrollment.",
        ),
        (
            "benefits.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            minimal_docx_bytes(),
            "Coverage begins after enrollment.",
        ),
        (
            "benefits.pdf",
            "application/pdf",
            minimal_pdf_bytes(),
            "Coverage begins after enrollment",
        ),
    ],
)
def test_extracts_representative_supported_document(
    tmp_path: Path,
    filename: str,
    media_type: str,
    content: bytes,
    expected_text: str,
) -> None:
    source = tmp_path / filename
    source.write_bytes(content)

    extracted = extract_document(source, media_type, filename, EXTRACTION_CONFIG)

    assert extracted.title == "benefits"
    assert expected_text in "\n".join(block.content for block in extracted.blocks)
    assert all(block.offset_start is not None for block in extracted.blocks)


def test_markdown_retains_heading_path_and_content_types(tmp_path: Path) -> None:
    source = tmp_path / "structured.md"
    source.write_text(
        "# Handbook\n\n"
        "## Eligibility\n\n"
        "- Full-time employees\n"
        "- Dependents\n\n"
        "```text\nCODE-42\n```\n",
        encoding="utf-8",
    )

    extracted = extract_document(source, "text/markdown", source.name, EXTRACTION_CONFIG)

    eligibility = next(block for block in extracted.blocks if "Full-time" in block.content)
    code = next(block for block in extracted.blocks if "CODE-42" in block.content)
    assert eligibility.heading_path == ["Handbook", "Eligibility"]
    assert eligibility.content_type == "list"
    assert code.heading_path == ["Handbook", "Eligibility"]
    assert code.content_type == "code"
