"""Texto plano / Markdown -> ParsedDocument (el Markdown ya trae su jerarquía)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from unsa_mind.domain.entities import ParsedDocument, RawDocument, sha256
from unsa_mind.domain.errors import ParseError

_TYPES = {"text/plain", "text/markdown"}


class TextParser:
    def supports(self, content_type: str) -> bool:
        return content_type.split(";")[0].strip().lower() in _TYPES

    def parse(self, raw: RawDocument, *, base_metadata: dict) -> ParsedDocument:
        try:
            markdown = raw.body.decode("utf-8-sig")
        except UnicodeDecodeError:
            markdown = raw.body.decode("latin-1")
        markdown = markdown.replace("\r\n", "\n").strip()
        if not markdown:
            raise ParseError("archivo de texto vacío")
        heading = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
        title = heading.group(1).strip() if heading else Path(unquote(urlsplit(raw.url).path)).stem
        return ParsedDocument(
            source_id=raw.source_id,
            url=raw.url,
            title=title,
            markdown=markdown,
            content_hash=sha256(markdown),
            metadata={**base_metadata},
            fetched_at=raw.fetched_at,
        )
