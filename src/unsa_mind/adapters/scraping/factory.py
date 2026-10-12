from __future__ import annotations

from unsa_mind.adapters.scraping.html_parser import HtmlParser
from unsa_mind.adapters.scraping.pdf_parser import PdfParser
from unsa_mind.application.ports.scraping import FetcherPort, ParserPort
from unsa_mind.config.settings import Settings


def build_fetcher(settings: Settings) -> FetcherPort:
    if settings.fetcher == "scrapling":
        from unsa_mind.adapters.scraping.scrapling_fetcher import ScraplingFetcher

        return ScraplingFetcher(settings)
    from unsa_mind.adapters.scraping.httpx_fetcher import HttpxFetcher

    return HttpxFetcher(settings)


def build_parsers(settings: Settings) -> list[ParserPort]:
    return [HtmlParser(), PdfParser()]
