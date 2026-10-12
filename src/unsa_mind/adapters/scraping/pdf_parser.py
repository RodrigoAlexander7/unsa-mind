"""PDF -> Markdown estructurado (TÍTULO/CAPÍTULO/Artículo -> #/##/###)."""

from __future__ import annotations

import io
import math
import re
from collections import Counter

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from unsa_mind.domain.entities import ParsedDocument, RawDocument, sha256
from unsa_mind.domain.errors import ParseError

_PAGE_NUM = re.compile(
    r"^\s*(?:[-–—]\s*)?(?:p[áa]g(?:ina|\.)?\s*)?\d{1,4}(?:\s*(?:de|/)\s*\d{1,4})?(?:\s*[-–—])?\s*$",
    re.IGNORECASE,
)
_TITULO = re.compile(r"^T[ÍI]TULO\s+([IVXLCDM]+|\d+|[ÚU]NICO|PRELIMINAR)\b(.*)$", re.IGNORECASE)
_CAPITULO = re.compile(r"^CAP[ÍI]TULO\s+([IVXLCDM]+|\d+|[ÚU]NICO)\b(.*)$", re.IGNORECASE)
_ARTICULO = re.compile(r"^(Art[íi]culo|Art\.)\s*(\d+[°ºo]?(?:-?[A-Z])?)\s*[.:\-–—]*\s*(.*)$", re.IGNORECASE)


def _key(line: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line.strip().lower()))


def _is_caps_title(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and len(line) <= 80 and all(c.isupper() for c in letters)


class PdfParser:
    def supports(self, content_type: str) -> bool:
        return content_type.split(";")[0].strip().lower() == "application/pdf"

    def parse(self, raw: RawDocument, *, base_metadata: dict) -> ParsedDocument:
        try:
            reader = PdfReader(io.BytesIO(raw.body))
            pages = [(p.extract_text() or "") for p in reader.pages]
            meta_title = (reader.metadata.title if reader.metadata else None) or ""
        except (PyPdfError, ValueError, OSError, KeyError) as exc:
            raise ParseError(f"PDF ilegible: {exc}") from exc
        if not any(p.strip() for p in pages):
            raise ParseError(
                "El PDF no contiene texto extraíble (probablemente escaneado); el OCR no está soportado."
            )
        page_lines = [[ln.rstrip() for ln in p.splitlines() if ln.strip()] for p in pages]
        page_lines = self._strip_repeated(page_lines)
        lines = [ln for pl in page_lines for ln in pl]
        markdown = self._structure(lines)
        if not markdown.strip():
            raise ParseError("PDF sin contenido textual tras la limpieza")
        title = str(meta_title).strip()
        if not title:
            m = re.search(r"^#+\s+(.+)$", markdown, re.MULTILINE)
            title = m.group(1).strip() if m else lines[0].strip()
        return ParsedDocument(
            source_id=raw.source_id,
            url=raw.url,
            title=title,
            markdown=markdown,
            content_hash=sha256(markdown),
            metadata={**base_metadata, "pages": len(pages)},
            fetched_at=raw.fetched_at,
        )

    @staticmethod
    def _strip_repeated(pages: list[list[str]]) -> list[list[str]]:
        n = len(pages)
        cleaned = [[ln for ln in pl if not _PAGE_NUM.match(ln)] for pl in pages]
        if n >= 2:
            counts: Counter[str] = Counter()
            for pl in cleaned:
                edge = pl[:2] + pl[-2:] if len(pl) > 4 else pl
                counts.update({_key(ln) for ln in edge})
            threshold = max(2, math.ceil(n * 0.6))
            repeated = {k for k, c in counts.items() if c >= threshold}
            cleaned = [
                [ln for i, ln in enumerate(pl) if not (_key(ln) in repeated and (i < 2 or i >= len(pl) - 2))]
                for pl in cleaned
            ]
        return cleaned

    @staticmethod
    def _structure(lines: list[str]) -> str:
        out: list[str] = []
        para: list[str] = []

        def flush() -> None:
            if para:
                out.append(" ".join(para))
                para.clear()

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            m_t, m_c, m_a = _TITULO.match(line), _CAPITULO.match(line), _ARTICULO.match(line)
            if m_t or m_c:
                flush()
                level = "#" if m_t else "##"
                head = line
                if i + 1 < len(lines):
                    nxt = lines[i + 1].strip()
                    if _is_caps_title(nxt) and not (_TITULO.match(nxt) or _CAPITULO.match(nxt)):
                        head = f"{line} - {nxt}"
                        i += 1
                out.append(f"{level} {head}")
            elif m_a:
                flush()
                num, rest = m_a.group(2), m_a.group(3).strip()
                if rest and len(rest) <= 80 and not rest.endswith((".", ";", ",")):
                    out.append(f"### Artículo {num}. {rest}")
                else:
                    out.append(f"### Artículo {num}")
                    if rest:
                        para.append(rest)
            else:
                para.append(line)
                if line.endswith((".", ":", ";")):
                    flush()
            i += 1
        flush()
        return "\n\n".join(out)
