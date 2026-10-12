from __future__ import annotations

from typing import Protocol

from unsa_mind.domain.entities import ParsedDocument, RawDocument


class FetcherPort(Protocol):
    """Descarga una URL (HTML o PDF). Adaptadores: httpx, Scrapling."""

    async def fetch(self, url: str, *, source_id: str) -> RawDocument: ...


class ParserPort(Protocol):
    """Convierte un RawDocument en Markdown con jerarquía preservada."""

    def supports(self, content_type: str) -> bool: ...

    def parse(self, raw: RawDocument, *, base_metadata: dict) -> ParsedDocument: ...
