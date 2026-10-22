from __future__ import annotations

import logging

from unsa_mind.adapters.scraping.html_parser import HtmlParser
from unsa_mind.adapters.scraping.local_fetcher import LocalFileFetcher, RoutingFetcher
from unsa_mind.adapters.scraping.pdf_parser import PdfParser
from unsa_mind.adapters.scraping.text_parser import TextParser
from unsa_mind.application.ports.scraping import FetcherPort, ParserPort
from unsa_mind.config.settings import Settings

log = logging.getLogger(__name__)


def build_fetcher(settings: Settings) -> FetcherPort:
    return RoutingFetcher(_build_web_fetcher(settings), LocalFileFetcher(settings.raw_dir))


def _build_web_fetcher(settings: Settings) -> FetcherPort:
    if settings.fetcher == "scrapling":
        from unsa_mind.adapters.scraping.scrapling_fetcher import ScraplingFetcher

        return ScraplingFetcher(settings)
    from unsa_mind.adapters.scraping.httpx_fetcher import HttpxFetcher

    return HttpxFetcher(settings)


def build_parsers(settings: Settings) -> list[ParserPort]:
    if settings.ocr_provider == "none":
        return [HtmlParser(), PdfParser(), TextParser()]
    from unsa_mind.adapters.scraping.pdf_ocr import PdfOcr

    # Servicios distintos para PDF y para Office: cada uno lleva contadores por documento y las
    # fuentes se procesan en paralelo.
    pdf_ocr = PdfOcr(
        _build_ocr_service(settings),
        max_pages=_max_pages(settings),
        workers=settings.ocr_concurrency,
        dpi=300 if settings.ocr_provider == "tesseract" else 200,
    )
    parsers: list[ParserPort] = [HtmlParser(), PdfParser(ocr=pdf_ocr.ocr_pdf_text), TextParser()]
    try:
        from unsa_mind.adapters.scraping.markitdown_engine import MarkItDownEngine, OfficeParser

        parsers.append(OfficeParser(MarkItDownEngine(_build_ocr_service(settings))))
    except RuntimeError as exc:  # MarkItDown es opcional: sin él solo se pierde Office
        log.warning("DOCX/PPTX/XLSX no disponibles: %s", exc)
    return parsers


def _max_pages(settings: Settings) -> int:
    """0 = automático: 80 con `agy` (lento y con cuota), 1000 con Tesseract (local)."""
    return settings.ocr_max_pages or (1000 if settings.ocr_provider == "tesseract" else 80)


def _build_ocr_service(settings: Settings):
    if settings.ocr_provider == "tesseract":
        from unsa_mind.adapters.scraping.tesseract_ocr import TesseractOcrService

        service = TesseractOcrService(
            settings.ocr_lang,
            tesseract_bin=settings.tesseract_bin,
            timeout_s=settings.ocr_timeout_s,
            max_images=_max_pages(settings),
        )
        service.check()  # falta el binario o el idioma: se informa al arrancar, no página a página
        return service
    from unsa_mind.adapters.scraping.agy_ocr import AgyOcrService

    return AgyOcrService(
        settings.ocr_model,
        agy_bin=settings.agy_bin,
        timeout_s=settings.ocr_timeout_s,
        max_images=_max_pages(settings),
        cache_dir=settings.data_dir / "ocr_cache",  # reintentos sin repetir páginas ya hechas
    )
