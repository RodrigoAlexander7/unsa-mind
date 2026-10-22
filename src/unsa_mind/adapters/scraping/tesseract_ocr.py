"""OCR clásico local con Tesseract: rápido, sin red ni cuota, resultado determinista.

Requiere el binario del sistema y el idioma (Debian/Ubuntu: `sudo apt install tesseract-ocr
tesseract-ocr-spa`). No añade dependencias de Python: se invoca como subproceso.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, BinaryIO

from .agy_ocr import OcrResult, _extension

log = logging.getLogger(__name__)


class TesseractOcrService:
    def __init__(
        self,
        lang: str = "spa",
        *,
        tesseract_bin: str = "tesseract",
        timeout_s: float = 120.0,
        max_images: int = 1000,
    ) -> None:
        self.lang = lang
        self._bin = shutil.which(tesseract_bin) or tesseract_bin
        self._timeout = timeout_s
        self._max_images = max_images
        self._lock = threading.Lock()
        self._calls = 0
        self.errors: list[str] = []

    def reset(self) -> None:
        with self._lock:
            self._calls = 0
            self.errors = []

    def check(self) -> None:
        """Falla pronto y con un mensaje claro si falta el binario o el idioma."""
        try:
            out = subprocess.run(
                [self._bin, "--list-langs"], capture_output=True, text=True, timeout=30, check=False
            )
        except OSError as exc:
            raise RuntimeError(
                f"Tesseract no está disponible ('{self._bin}'): instálelo con "
                "`sudo apt install tesseract-ocr tesseract-ocr-spa` o ajuste UNSA_TESSERACT_BIN"
            ) from exc
        langs = set((out.stdout + out.stderr).split())
        missing = [code for code in self.lang.split("+") if code not in langs]
        if missing:
            raise RuntimeError(
                f"Tesseract no tiene el idioma {missing}: instale el paquete tesseract-ocr-<idioma> "
                f"(disponibles: {sorted(langs - {'List', 'of', 'available', 'languages'})[:10]}…)"
            )

    def extract_text(self, image_stream: BinaryIO, *args: Any, **kwargs: Any) -> OcrResult:
        with self._lock:
            self._calls += 1
            n = self._calls
        if n > self._max_images:
            return self._fail(f"se superó el máximo de {self._max_images} imágenes por documento", once=n)
        image_stream.seek(0)
        data = image_stream.read()
        image_stream.seek(0)
        log.info("OCR (tesseract %s): imagen %d …", self.lang, n)
        with tempfile.TemporaryDirectory(prefix="unsa-ocr-") as tmp:
            path = Path(tmp) / f"page{_extension(data)}"
            path.write_bytes(data)
            env = {**os.environ, "OMP_THREAD_LIMIT": "1"}  # el paralelismo lo da PdfOcr
            try:
                proc = subprocess.run(
                    [self._bin, str(path), "stdout", "-l", self.lang],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=self._timeout, check=False, env=env,
                )  # fmt: skip
            except subprocess.TimeoutExpired:
                return self._fail(f"tesseract: timeout tras {self._timeout}s")
            except OSError as exc:
                return self._fail(f"tesseract: no se pudo ejecutar '{self._bin}' ({exc})")
        if proc.returncode != 0:
            return self._fail(f"tesseract: código {proc.returncode} ({proc.stderr.strip()[:200]})")
        return OcrResult(text=proc.stdout.strip(), backend_used="tesseract")

    def _fail(self, message: str, once: int | None = None) -> OcrResult:
        if once is not None and once > self._max_images + 1:
            return OcrResult(text="", error=message, backend_used="tesseract")
        log.warning("OCR tesseract: %s", message)
        with self._lock:
            self.errors.append(message)
        return OcrResult(text="", error=message, backend_used="tesseract")
