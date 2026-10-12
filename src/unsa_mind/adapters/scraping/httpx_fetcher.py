"""Fetcher basado en httpx: cortés (retardo por dominio, robots.txt) y resiliente."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from unsa_mind.adapters.scraping.links import base_content_type, extract_links
from unsa_mind.config.settings import Settings
from unsa_mind.domain.entities import RawDocument
from unsa_mind.domain.errors import FetchError

_RETRY_STATUS = {429, 500, 502, 503, 504}
_HTML_TYPES = ("text/html", "application/xhtml+xml")


class _Retryable(Exception):
    pass


class HttpxFetcher:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        *,
        max_bytes: int = 25 * 1024 * 1024,
        max_retries: int = 3,
        backoff_s: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(follow_redirects=True, timeout=30.0)
        self._owns_client = client is None
        self._max_bytes = max_bytes
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep
        self._last_hit: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch(self, url: str, *, source_id: str) -> RawDocument:
        host = urlsplit(url).netloc.lower()
        if not host:
            raise FetchError(f"URL inválida: {url}")
        if self._settings.respect_robots and not await self._allowed(url):
            raise FetchError(f"robots.txt no permite acceder a {url}")

        response, body = await self._get_with_retries(url, host)
        content_type = base_content_type(response.headers.get("content-type"), str(response.url))
        links: tuple[str, ...] = ()
        if content_type in _HTML_TYPES:
            links = extract_links(body, str(response.url))
        return RawDocument(
            source_id=source_id,
            url=str(response.url),
            content_type=content_type,
            body=body,
            links=links,
        )

    async def _polite_wait(self, host: str) -> None:
        delay = self._settings.request_delay_s
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            if delay > 0 and host in self._last_hit:
                wait = delay - (time.monotonic() - self._last_hit[host])
                if wait > 0:
                    await self._sleep(wait)
            self._last_hit[host] = time.monotonic()

    async def _get_with_retries(self, url: str, host: str) -> tuple[httpx.Response, bytes]:
        last_error = "desconocido"
        for attempt in range(self._max_retries + 1):
            if attempt:
                await self._sleep(self._backoff_s * (2 ** (attempt - 1)))
            await self._polite_wait(host)
            try:
                return await self._get_once(url)
            except _Retryable as exc:
                last_error = str(exc)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        raise FetchError(f"No se pudo descargar {url} tras reintentos: {last_error}")

    async def _get_once(self, url: str) -> tuple[httpx.Response, bytes]:
        try:
            async with self._client.stream(
                "GET", url, headers={"User-Agent": self._settings.user_agent}, follow_redirects=True
            ) as response:
                if response.status_code in _RETRY_STATUS:
                    raise _Retryable(f"HTTP {response.status_code}")
                if response.status_code >= 400:
                    raise FetchError(f"HTTP {response.status_code} en {url}")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > self._max_bytes:
                    raise FetchError(f"{url} excede el tamaño máximo ({declared} bytes)")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise FetchError(f"{url} excede el tamaño máximo ({self._max_bytes} bytes)")
                    chunks.append(chunk)
                return response, b"".join(chunks)
        except (FetchError, _Retryable, httpx.TransportError):
            raise
        except httpx.HTTPError as exc:
            raise FetchError(f"Error HTTP en {url}: {exc}") from exc

    async def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc.lower()}"
        if origin not in self._robots:
            self._robots[origin] = await self._load_robots(origin)
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self._settings.user_agent, url)

    async def _load_robots(self, origin: str) -> RobotFileParser | None:
        try:
            resp = await self._client.get(
                f"{origin}/robots.txt", headers={"User-Agent": self._settings.user_agent}
            )
        except httpx.HTTPError:
            return None  # robots inaccesible => se asume permitido
        parser = RobotFileParser()
        if resp.status_code in (401, 403):
            parser.disallow_all = True
            return parser
        if resp.status_code >= 400:
            return None
        parser.parse(resp.text.splitlines())
        return parser
