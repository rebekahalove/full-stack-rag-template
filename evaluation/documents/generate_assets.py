"""Reproducibly build the synthetic PDF and DOCX evaluation fixtures.

The generator uses only Python's standard library. Run it from any directory:

    python evaluation/documents/generate_assets.py

Generated ZIP members use a fixed timestamp, and the PDF contains no timestamps or
random identifiers, so identical source files produce identical output bytes.
"""

from __future__ import annotations

import json
import textwrap
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf() -> None:
    source = (ROOT / "orion_operations_guide.source.txt").read_text(encoding="utf-8")
    pages = source.split("\f")
    objects: dict[int, bytes] = {}
    page_ids: list[int] = []
    font_id = 3 + len(pages) * 2

    for index, page in enumerate(pages):
        page_id = 3 + index * 2
        content_id = page_id + 1
        page_ids.append(page_id)
        lines: list[str] = []
        for paragraph in page.splitlines():
            if not paragraph.strip():
                lines.append("")
            else:
                lines.extend(
                    textwrap.wrap(paragraph.strip(), width=82, break_on_hyphens=False)
                )
        commands = ["BT", "/F1 10 Tf", "54 738 Td", "14 TL"]
        for line in lines:
            commands.append(f"({_pdf_escape(line)}) Tj")
            commands.append("T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )

    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode(
        "ascii"
    )
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, font_id + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {font_id + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {font_id + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    (ROOT / "orion_operations_guide.pdf").write_bytes(output)


def _paragraph(text: str, style: str | None = None) -> str:
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{style_xml}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"


def _table(rows: list[list[str]]) -> str:
    body = []
    for row in rows:
        cells = "".join(
            f"<w:tc><w:tcPr/><w:p><w:r><w:t>{escape(cell)}</w:t></w:r></w:p></w:tc>"
            for cell in row
        )
        body.append(f"<w:tr>{cells}</w:tr>")
    return "<w:tbl><w:tblPr/><w:tblGrid/>" + "".join(body) + "</w:tbl>"


def _zip_member(archive: zipfile.ZipFile, name: str, content: str) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content.encode("utf-8"))


def build_docx() -> None:
    data = json.loads(
        (ROOT / "atlas_project_brief.source.json").read_text(encoding="utf-8")
    )
    blocks = [_paragraph(data["title"], "Heading1")]
    for section in data["sections"]:
        blocks.append(_paragraph(section["heading"], "Heading2"))
        blocks.extend(_paragraph(value) for value in section.get("paragraphs", []))
        if "table" in section:
            blocks.append(_table(section["table"]))
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(blocks)}<w:sectPr/></w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1">'
        '<w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
        '<w:qFormat/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading2">'
        '<w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>'
        '<w:qFormat/><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>'
        "</w:styles>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    package_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>'
    )
    output = ROOT / "atlas_project_brief.docx"
    with zipfile.ZipFile(output, "w") as archive:
        _zip_member(archive, "[Content_Types].xml", content_types)
        _zip_member(archive, "_rels/.rels", package_rels)
        _zip_member(archive, "word/_rels/document.xml.rels", document_rels)
        _zip_member(archive, "word/document.xml", document_xml)
        _zip_member(archive, "word/styles.xml", styles_xml)


if __name__ == "__main__":
    build_pdf()
    build_docx()
    print("Generated orion_operations_guide.pdf and atlas_project_brief.docx")
