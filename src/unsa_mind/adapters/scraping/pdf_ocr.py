"""OCR de PDF escaneados: UNA llamada de OCR por página, en paralelo y con tope previo.

Independiente del motor (`agy`, Tesseract...): recibe cualquier servicio con
`extract_text(BytesIO) -> resultado(.text/.error)`, `reset()` y `.errors`. Solo necesita PyMuPDF
para renderizar las páginas (extra `ocr-light`).
"""

from __future__ import annotations

import io
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from unsa_mind.domain.errors import ParseError


class PdfOcr:
    def __init__(self, service: Any, *, max_pages: int, workers: int = 3, dpi: int = 200) -> None:
        self._svc = service
        self._max_pages = max_pages
        self._workers = max(1, workers)
        self._dpi = dpi
        self._lock = threading.Lock()  # los servicios llevan contadores por documento

    def ocr_pdf_text(self, body: bytes) -> str:
        """`## Page N` + texto de cada página; `PdfParser` lo limpia y estructura."""
        try:
            import pymupdf  # extra `ocr-light` (o `ocr`)

            doc = pymupdf.open(stream=body, filetype="pdf")
        except ImportError as exc:
            raise ParseError("El OCR de PDF requiere PyMuPDF: pip install -e '.[ocr-light]'") from exc
        except Exception as exc:
            raise ParseError(f"PDF ilegible para OCR: {exc}") from exc
        n = doc.page_count
        if n > self._max_pages:
            doc.close()
            raise ParseError(
                f"El PDF tiene {n} páginas y el máximo para OCR es {self._max_pages} "
                "(suba UNSA_OCR_MAX_PAGES o divida el documento)"
            )
        images = [doc[i].get_pixmap(dpi=self._dpi).tobytes("png") for i in range(n)]
        doc.close()
        with self._lock:
            self._svc.reset()
            with ThreadPoolExecutor(max_workers=self._workers) as pool:
                results = list(pool.map(lambda b: self._svc.extract_text(io.BytesIO(b)), images))
            errors = list(self._svc.errors)
        if errors:  # nunca se indexa una norma con páginas sin transcribir
            raise ParseError(f"OCR incompleto ({len(errors)} fallo(s) en {n} páginas): {errors[0]}")
        return "\n\n".join(f"## Page {i}\n\n{r.text}" for i, r in enumerate(results, 1))
