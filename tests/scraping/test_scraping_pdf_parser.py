from __future__ import annotations

import pytest

from unsa_mind.adapters.scraping.pdf_parser import PdfParser
from unsa_mind.domain.entities import RawDocument
from unsa_mind.domain.errors import ParseError


def build_pdf(pages: list[list[str]]) -> bytes:
    """PDF mínimo escrito a mano (Helvetica, WinAnsi) con una línea por elemento."""
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    font_id = 3 + 2 * n
    for i, lines in enumerate(pages):
        content_id = 4 + 2 * i
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        ops = ["BT", "/F1 11 Tf", "14 TL", "50 750 Td"]
        for ln in lines:
            esc = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"({esc}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("cp1252")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(out)


def parse(pdf: bytes):
    raw = RawDocument(source_id="s", url="https://unsa.edu.pe/r.pdf", content_type="application/pdf", body=pdf)
    return PdfParser().parse(raw, base_metadata={"tipo_doc": "reglamento"})


def test_structure_and_noise_removal():
    pages = [
        [
            "UNIVERSIDAD NACIONAL DE SAN AGUSTIN",
            "TÍTULO I",
            "DISPOSICIONES GENERALES",
            "CAPÍTULO I",
            "DEL OBJETO",
            "Artículo 1.- Objeto",
            "El presente reglamento regula la matrícula.",
            "Artículo 2.- El estudiante debe presentar su DNI al momento de matricularse.",
            "Página 1 de 3",
        ],
        [
            "UNIVERSIDAD NACIONAL DE SAN AGUSTIN",
            "Artículo 3.- Plazos",
            "Los plazos se publican en el calendario.",
            "Página 2 de 3",
        ],
        [
            "UNIVERSIDAD NACIONAL DE SAN AGUSTIN",
            "CAPÍTULO II",
            "Artículo 4.- Sanciones",
            "Se aplican según norma.",
            "3",
        ],
    ]
    doc = parse(build_pdf(pages))
    md = doc.markdown
    assert "# TÍTULO I - DISPOSICIONES GENERALES" in md
    assert "\n## CAPÍTULO I - DEL OBJETO" in md
    assert "### Artículo 1. Objeto" in md
    assert "### Artículo 2\n" in md and "El estudiante debe presentar su DNI" in md
    assert "### Artículo 4. Sanciones" in md
    assert "## CAPÍTULO II" in md
    assert "UNIVERSIDAD NACIONAL" not in md
    assert "Página" not in md
    assert md.splitlines()[-1] == "Se aplican según norma."
    assert doc.metadata["pages"] == 3 and doc.metadata["tipo_doc"] == "reglamento"
    assert doc.title == "TÍTULO I - DISPOSICIONES GENERALES"
    assert doc.content_hash == parse(build_pdf(pages)).content_hash


def test_works_with_structural_chunker():
    from unsa_mind.application.services import chunker

    doc = parse(build_pdf([["TÍTULO I", "Artículo 1.- Objeto", "Texto uno.", "Artículo 2.- Alcance", "Texto dos."]]))
    assert chunker is not None
    assert "### Artículo 1. Objeto" in doc.markdown and "### Artículo 2. Alcance" in doc.markdown


def test_scanned_pdf_raises_clear_error():
    with pytest.raises(ParseError, match="OCR"):
        parse(build_pdf([[""], [""]]))


def test_garbage_raises_parse_error():
    with pytest.raises(ParseError):
        parse(b"esto no es un pdf")


def test_supports():
    p = PdfParser()
    assert p.supports("application/pdf") and not p.supports("text/html")
