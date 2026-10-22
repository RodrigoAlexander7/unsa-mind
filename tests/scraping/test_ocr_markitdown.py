from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from unsa_mind.adapters.scraping.agy_ocr import AgyOcrService
from unsa_mind.adapters.scraping.factory import build_parsers
from unsa_mind.adapters.scraping.pdf_parser import PdfParser
from unsa_mind.config.settings import Settings
from unsa_mind.domain.entities import RawDocument
from unsa_mind.domain.errors import ParseError

FAKE = Path(__file__).with_name("fake_agy_ocr.py")


@pytest.fixture
def fake_bin(tmp_path: Path) -> str:
    if os.name == "nt":
        path = tmp_path / "agy.cmd"
        path.write_text(f'@echo off\r\n"{sys.executable}" "{FAKE}" %*\r\n')
    else:
        path = tmp_path / "agy"
        path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buf, format="PNG")
    return buf.getvalue()


def scanned_pdf(pages: int = 2) -> bytes:
    """PDF de solo imágenes (sin texto extraíble), como un escaneo."""
    from PIL import Image

    imgs = [Image.new("RGB", (300, 400), "white") for _ in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="PDF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


def test_agy_ocr_service_ok_and_flags(fake_bin, tmp_path, monkeypatch):
    log = tmp_path / "log.json"
    monkeypatch.setenv("FAKE_AGY_LOG", str(log))
    svc = AgyOcrService("gemini-3.8-flash-medium", agy_bin=fake_bin, timeout_s=20)
    res = svc.extract_text(io.BytesIO(png_bytes()))
    assert res.error is None and "Artículo 1" in res.text
    argv = json.loads(log.read_text(encoding="utf-8"))["argv"]
    assert argv[argv.index("--model") + 1] == "gemini-3.8-flash-medium"
    assert "--sandbox" in argv and "--add-dir" in argv and "--disable-slash-commands" in argv


def test_agy_ocr_service_errors_and_limit(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "503")
    svc = AgyOcrService(agy_bin=fake_bin, timeout_s=20, retries=1, backoff_s=0)
    res = svc.extract_text(io.BytesIO(png_bytes()))
    assert res.text == "" and "503" in res.error and svc.errors
    svc.reset()
    assert svc.errors == []
    monkeypatch.setenv("FAKE_AGY_MODE", "garbage")
    assert "no válida" in AgyOcrService(agy_bin=fake_bin, retries=0).extract_text(io.BytesIO(png_bytes())).error
    monkeypatch.setenv("FAKE_AGY_MODE", "ok")
    limited = AgyOcrService(agy_bin=fake_bin, max_images=1)
    assert limited.extract_text(io.BytesIO(png_bytes())).error is None
    assert "máximo" in limited.extract_text(io.BytesIO(png_bytes())).error


def test_scanned_pdf_without_ocr_explains_how_to_enable():
    raw = RawDocument("s", "file:///x.pdf", "application/pdf", scanned_pdf())
    with pytest.raises(ParseError, match="UNSA_OCR_PROVIDER"):
        PdfParser().parse(raw, base_metadata={})


def test_scanned_pdf_with_ocr_end_to_end(fake_bin, tmp_path):
    pytest.importorskip("markitdown_ocr")
    pytest.importorskip("pdfplumber")
    settings = Settings(_env_file=None, data_dir=tmp_path, ocr_provider="agy", agy_bin=fake_bin, ocr_timeout_s=20)
    parsers = build_parsers(settings)
    pdf = next(p for p in parsers if p.supports("application/pdf"))
    raw = RawDocument("s", "file:///escaneo.pdf", "application/pdf", scanned_pdf(2))
    parsed = pdf.parse(raw, base_metadata={"origen": "local"})
    assert parsed.metadata["ocr"] is True and parsed.metadata["pages"] == 2
    assert "### Artículo 1" in parsed.markdown and "Texto escaneado" in parsed.markdown
    assert "Image OCR" not in parsed.markdown and "## Page" not in parsed.markdown


def test_page_limit_checked_before_any_ocr_call(fake_bin, tmp_path, monkeypatch):
    pytest.importorskip("markitdown_ocr")
    log = tmp_path / "log.json"
    monkeypatch.setenv("FAKE_AGY_LOG", str(log))
    settings = Settings(_env_file=None, data_dir=tmp_path, ocr_provider="agy", agy_bin=fake_bin, ocr_max_pages=2)
    pdf = next(p for p in build_parsers(settings) if p.supports("application/pdf"))
    raw = RawDocument("s", "file:///grande.pdf", "application/pdf", scanned_pdf(3))
    with pytest.raises(ParseError, match="3 páginas.*máximo.*2"):
        pdf.parse(raw, base_metadata={})
    assert not log.exists()  # agy ni siquiera se invocó


def test_ocr_cache_lets_a_retry_skip_finished_pages(fake_bin, tmp_path, monkeypatch):
    svc = AgyOcrService(agy_bin=fake_bin, timeout_s=20, retries=0, cache_dir=tmp_path / "cache")
    first = svc.extract_text(io.BytesIO(png_bytes()))
    assert first.error is None
    monkeypatch.setenv("FAKE_AGY_MODE", "503")  # ahora agy fallaría...
    svc.reset()
    again = svc.extract_text(io.BytesIO(png_bytes()))
    assert again.error is None and again.text == first.text  # ...pero sale de la caché


def test_scanned_pdf_with_failing_ocr_is_not_indexed(fake_bin, tmp_path, monkeypatch):
    pytest.importorskip("markitdown_ocr")
    monkeypatch.setenv("FAKE_AGY_MODE", "503")
    settings = Settings(_env_file=None, data_dir=tmp_path, ocr_provider="agy", agy_bin=fake_bin, ocr_timeout_s=20)
    pdf = next(p for p in build_parsers(settings) if p.supports("application/pdf"))
    raw = RawDocument("s", "file:///escaneo.pdf", "application/pdf", scanned_pdf(1))
    with pytest.raises(ParseError, match="OCR incompleto"):
        pdf.parse(raw, base_metadata={})


def test_office_parser_registered_and_docx_converted(fake_bin, tmp_path):
    pytest.importorskip("markitdown_ocr")
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Reglamento de prueba", 1)
    d.add_paragraph("Artículo 1. Contenido en Word.")
    buf = io.BytesIO()
    d.save(buf)
    settings = Settings(_env_file=None, data_dir=tmp_path, ocr_provider="agy", agy_bin=fake_bin)
    parsers = build_parsers(settings)
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    office = next(p for p in parsers if p.supports(mime))
    parsed = office.parse(RawDocument("s", "file:///r.docx", mime, buf.getvalue()), base_metadata={})
    assert "Reglamento de prueba" in parsed.title and "Contenido en Word" in parsed.markdown
