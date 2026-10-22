"""MarkItDown + markitdown-ocr: Office (DOCX/PPTX/XLSX), con OCR de las imágenes incrustadas.

`markitdown`/`markitdown-ocr` son un extra opcional (`pip install -e ".[ocr]"`). El OCR de PDF
escaneados NO pasa por aquí (ver `pdf_ocr.py`: una llamada por página, con tope previo).
"""

from __future__ import annotations

import io
import threading
from typing import Any

from unsa_mind.domain.entities import ParsedDocument, RawDocument, sha256
from unsa_mind.domain.errors import ParseError

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_EXT = {DOCX: ".docx", PPTX: ".pptx", XLSX: ".xlsx"}


class MarkItDownEngine:
    """Convierte Office a Markdown. El OCR (si hay servicio) reemplaza a los conversores base."""

    def __init__(self, ocr_service: Any | None = None) -> None:
        try:
            from markitdown import MarkItDown
            from markitdown_ocr._docx_converter_with_ocr import DocxConverterWithOCR
            from markitdown_ocr._pdf_converter_with_ocr import PdfConverterWithOCR
            from markitdown_ocr._pptx_converter_with_ocr import PptxConverterWithOCR
            from markitdown_ocr._xlsx_converter_with_ocr import XlsxConverterWithOCR
        except ImportError as exc:
            raise RuntimeError("Office/OCR de imágenes requiere MarkItDown: pip install -e '.[ocr]'") from exc
        self._ocr = ocr_service
        self._lock = threading.Lock()  # MarkItDown y el servicio de OCR: una conversión a la vez
        self._md = MarkItDown(enable_plugins=False)
        if ocr_service is not None:  # mismo registro que el plugin oficial, con nuestro servicio
            for conv in (PdfConverterWithOCR, DocxConverterWithOCR, PptxConverterWithOCR, XlsxConverterWithOCR):
                self._md.register_converter(conv(ocr_service=ocr_service), priority=-1.0)

    def convert(self, body: bytes, content_type: str) -> str:
        from markitdown import StreamInfo

        info = StreamInfo(mimetype=content_type, extension=_EXT.get(content_type))
        with self._lock:
            if self._ocr is not None and hasattr(self._ocr, "reset"):
                self._ocr.reset()
            try:
                markdown = self._md.convert_stream(io.BytesIO(body), stream_info=info).markdown
            except Exception as exc:
                raise ParseError(f"MarkItDown no pudo convertir el documento: {exc}") from exc
            errors = list(getattr(self._ocr, "errors", []) or [])
        if errors:  # un documento con imágenes sin transcribir no se indexa a medias
            raise ParseError(f"OCR incompleto ({len(errors)} fallo(s)): {errors[0]}")
        return markdown


class OfficeParser:
    """DOCX/PPTX/XLSX -> Markdown vía MarkItDown."""

    def __init__(self, engine: MarkItDownEngine) -> None:
        self._engine = engine

    def supports(self, content_type: str) -> bool:
        return content_type.split(";")[0].strip().lower() in (DOCX, PPTX, XLSX)

    def parse(self, raw: RawDocument, *, base_metadata: dict) -> ParsedDocument:
        markdown = self._engine.convert(raw.body, raw.content_type.split(";")[0].strip().lower()).strip()
        if not markdown:
            raise ParseError("documento Office sin contenido textual")
        title = next((ln.lstrip("# ").strip() for ln in markdown.splitlines() if ln.strip()), raw.url)
        return ParsedDocument(
            source_id=raw.source_id,
            url=raw.url,
            title=title[:200],
            markdown=markdown,
            content_hash=sha256(markdown),
            metadata={**base_metadata},
            fetched_at=raw.fetched_at,
        )
