from __future__ import annotations

import io
import os
import stat
import sys
from pathlib import Path

import pytest

from unsa_mind.adapters.scraping.factory import build_parsers
from unsa_mind.adapters.scraping.tesseract_ocr import TesseractOcrService
from unsa_mind.config.settings import Settings
from unsa_mind.domain.entities import RawDocument
from unsa_mind.domain.errors import ParseError

FAKE = Path(__file__).with_name("fake_tesseract.py")


@pytest.fixture
def fake_tess(tmp_path: Path) -> str:
    if os.name == "nt":
        path = tmp_path / "tesseract.cmd"
        path.write_text(f'@echo off\r\n"{sys.executable}" "{FAKE}" %*\r\n')
    else:
        path = tmp_path / "tesseract"
        path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(buf, format="PNG")
    return buf.getvalue()


def scanned_pdf(pages: int) -> bytes:
    from PIL import Image

    imgs = [Image.new("RGB", (120, 160), "white") for _ in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="PDF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


def settings(tmp_path: Path, fake_tess: str, **kw) -> Settings:
    # Valores explícitos: importar markitdown carga el `.env` del proyecto en os.environ y, sin
    # esto, el UNSA_OCR_* del desarrollador se filtraría a los tests.
    base = {"ocr_max_pages": 0, "ocr_lang": "spa", "ocr_concurrency": 3, "ocr_timeout_s": 120.0}
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        ocr_provider="tesseract",
        tesseract_bin=fake_tess,
        **{**base, **kw},
    )


def test_service_ok_uses_language(fake_tess):
    svc = TesseractOcrService("spa+eng", tesseract_bin=fake_tess)
    res = svc.extract_text(io.BytesIO(png_bytes()))
    assert res.error is None and "Texto de Tesseract (spa+eng)" in res.text


def test_check_reports_missing_binary_and_language(fake_tess):
    TesseractOcrService("spa", tesseract_bin=fake_tess).check()  # spa existe en el falso
    with pytest.raises(RuntimeError, match="idioma"):
        TesseractOcrService("quz", tesseract_bin=fake_tess).check()
    with pytest.raises(RuntimeError, match="no está disponible"):
        TesseractOcrService("spa", tesseract_bin="/no/existe/tesseract").check()


def test_service_failure_is_recorded(fake_tess, monkeypatch):
    monkeypatch.setenv("FAKE_TESS_MODE", "fail")
    svc = TesseractOcrService(tesseract_bin=fake_tess)
    res = svc.extract_text(io.BytesIO(png_bytes()))
    assert res.text == "" and "código 1" in res.error and svc.errors
    svc.reset()
    assert svc.errors == []


def test_scanned_pdf_with_tesseract_end_to_end(fake_tess, tmp_path):
    pytest.importorskip("pymupdf")
    pdf = next(p for p in build_parsers(settings(tmp_path, fake_tess)) if p.supports("application/pdf"))
    raw = RawDocument("s", "file:///escaneo.pdf", "application/pdf", scanned_pdf(3))
    parsed = pdf.parse(raw, base_metadata={})
    assert parsed.metadata["ocr"] is True and parsed.metadata["pages"] == 3
    assert "### Artículo 1" in parsed.markdown and "Texto de Tesseract" in parsed.markdown


def test_book_of_200_plus_pages_is_accepted_by_default(fake_tess, tmp_path):
    pytest.importorskip("pymupdf")
    pdf = next(p for p in build_parsers(settings(tmp_path, fake_tess)) if p.supports("application/pdf"))
    raw = RawDocument("s", "file:///libro.pdf", "application/pdf", scanned_pdf(205))
    assert pdf.parse(raw, base_metadata={}).metadata["pages"] == 205


def test_page_limit_and_failures_block_indexing(fake_tess, tmp_path, monkeypatch):
    pytest.importorskip("pymupdf")
    limited = next(
        p
        for p in build_parsers(settings(tmp_path, fake_tess, ocr_max_pages=2))
        if p.supports("application/pdf")
    )
    raw = RawDocument("s", "file:///x.pdf", "application/pdf", scanned_pdf(3))
    with pytest.raises(ParseError, match="3 páginas.*máximo.*2"):
        limited.parse(raw, base_metadata={})
    monkeypatch.setenv("FAKE_TESS_MODE", "fail")
    pdf = next(p for p in build_parsers(settings(tmp_path, fake_tess)) if p.supports("application/pdf"))
    with pytest.raises(ParseError, match="OCR incompleto"):
        pdf.parse(raw, base_metadata={})


def test_missing_tesseract_fails_at_startup(tmp_path):
    with pytest.raises(RuntimeError, match="Tesseract no está disponible"):
        build_parsers(settings(tmp_path, "/no/existe/tesseract"))
