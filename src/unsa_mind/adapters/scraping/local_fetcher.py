"""Fetcher de documentos locales (carpeta `raw_dir`) y enrutador web/local."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import unquote, urlsplit

from unsa_mind.application.ports.scraping import FetcherPort
from unsa_mind.domain.entities import DIRECTORY_CONTENT_TYPE, RawDocument
from unsa_mind.domain.errors import FetchError

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    # Office: requieren UNSA_OCR_PROVIDER (MarkItDown); sin él se informa "Sin parser"
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_WEB = ("http://", "https://")


class LocalFileFetcher:
    """Lee archivos o carpetas, pero solo dentro de `raw_dir` (evita leer rutas arbitrarias).

    Una ruta de carpeta devuelve un RawDocument sintético cuyos `links` son los archivos
    soportados (recursivo, sin ocultos); cada archivo se descarga luego con su `file://`.
    """

    def __init__(self, raw_dir: Path, *, max_bytes: int = 25 * 1024 * 1024) -> None:
        self._root = raw_dir.resolve()
        self._max_bytes = max_bytes

    def _resolve(self, url: str) -> Path:
        if url.startswith("file://"):
            path = Path(unquote(urlsplit(url).path))
        elif url.startswith("raw:"):  # relativo a raw_dir: `raw:` (toda la carpeta), `raw:normas`
            path = self._root / url[4:].lstrip("/")
        else:
            path = Path(url)
        path = path.resolve()
        if path != self._root and self._root not in path.parents:
            raise FetchError(f"Ruta fuera de la carpeta permitida ({self._root}): {url}")
        return path

    async def fetch(self, url: str, *, source_id: str) -> RawDocument:
        path = self._resolve(url)
        if path.is_dir():
            files = sorted(
                p.as_uri()
                for p in path.rglob("*")
                if p.is_file()
                and p.suffix.lower() in _CONTENT_TYPES
                and not any(part.startswith(".") for part in p.relative_to(path).parts)
            )
            return RawDocument(
                source_id=source_id,
                url=path.as_uri(),
                content_type=DIRECTORY_CONTENT_TYPE,
                body=b"",
                links=tuple(files),
            )
        content_type = _CONTENT_TYPES.get(path.suffix.lower())
        if content_type is None:
            raise FetchError(f"Formato local no soportado: {path.name}")
        if not path.is_file():
            raise FetchError(f"No existe el archivo: {path}")
        if path.stat().st_size > self._max_bytes:
            raise FetchError(f"Archivo demasiado grande: {path.name}")
        body = await asyncio.to_thread(path.read_bytes)
        return RawDocument(
            source_id=source_id, url=path.as_uri(), content_type=content_type, body=body
        )


class RoutingFetcher:
    """http(s) -> fetcher web; cualquier otra cosa (ruta o file://) -> fetcher local."""

    def __init__(self, web: FetcherPort, local: FetcherPort) -> None:
        self._web = web
        self._local = local

    async def fetch(self, url: str, *, source_id: str) -> RawDocument:
        target = self._web if url.lower().startswith(_WEB) else self._local
        return await target.fetch(url, source_id=source_id)

    async def aclose(self) -> None:
        close = getattr(self._web, "aclose", None)
        if close:
            await close()
