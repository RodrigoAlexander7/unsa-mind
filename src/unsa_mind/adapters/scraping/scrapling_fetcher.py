"""Fetcher opcional basado en Scrapling (extra `scrapling`). Import perezoso."""

from __future__ import annotations

import asyncio
from typing import Any

from unsa_mind.adapters.scraping.links import base_content_type, extract_links
from unsa_mind.config.settings import Settings
from unsa_mind.domain.entities import RawDocument
from unsa_mind.domain.errors import FetchError

_HTML_TYPES = ("text/html", "application/xhtml+xml")


def _load_scrapling() -> Any:
    try:
        import scrapling.fetchers as mod
    except ImportError:
        try:
            import scrapling as mod  # type: ignore[no-redef]
        except ImportError as exc:
            raise RuntimeError(
                "ScraplingFetcher requiere el extra opcional 'scrapling' "
                "(pip install scrapling). Usa UNSA_FETCHER=httpx si no lo necesitas."
            ) from exc
    return mod


class ScraplingFetcher:
    """`stealth=True` usa StealthyFetcher (navegador; sitios con anti-bot)."""

    def __init__(self, settings: Settings, *, stealth: bool = False, module: Any = None) -> None:
        self._settings = settings
        self._stealth = stealth
        mod = module or _load_scrapling()
        self._impl = mod.StealthyFetcher if stealth else mod.Fetcher

    def _sync_fetch(self, url: str) -> Any:
        if self._stealth:
            return self._impl.fetch(url, headless=True)
        return self._impl.get(url, headers={"User-Agent": self._settings.user_agent})

    async def fetch(self, url: str, *, source_id: str) -> RawDocument:
        try:
            page = await asyncio.to_thread(self._sync_fetch, url)
        except Exception as exc:  # noqa: BLE001 - la librería lanza tipos variados
            raise FetchError(f"Scrapling falló en {url}: {exc}") from exc
        status = int(getattr(page, "status", 200) or 200)
        if status >= 400:
            raise FetchError(f"HTTP {status} en {url}")
        body = getattr(page, "body", b"")
        if isinstance(body, str):
            body = body.encode("utf-8")
        headers = dict(getattr(page, "headers", None) or {})
        raw_ct = next((v for k, v in headers.items() if str(k).lower() == "content-type"), None)
        content_type = base_content_type(raw_ct, url)
        final_url = str(getattr(page, "url", None) or url)
        links = extract_links(body, final_url) if content_type in _HTML_TYPES else ()
        return RawDocument(
            source_id=source_id, url=final_url, content_type=content_type, body=bytes(body), links=links
        )
