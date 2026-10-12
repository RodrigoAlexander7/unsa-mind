"""Chunking estructural para reglamentos y documentos administrativos.

Estrategia: se parte por jerarquía de títulos Markdown y por "Artículo N". Cada artículo /
sección es una unidad; si excede `max_chars` se subdivide por párrafos con traslape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from unsa_mind.domain.entities import Authority, Chunk, ParsedDocument, sha256

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_ARTICLE = re.compile(r"^(?:\*\*)?(Art[íi]culo|Art\.)\s*\d+", re.IGNORECASE)


@dataclass(frozen=True)
class ChunkerConfig:
    max_chars: int = 2400  # ~600 tokens
    min_chars: int = 200
    overlap_chars: int = 240  # ~10 %


def _split_sections(markdown: str) -> list[tuple[str, str]]:
    """Devuelve [(ruta_jerárquica, texto)] respetando títulos y artículos."""
    stack: list[tuple[int, str]] = []
    sections: list[tuple[str, list[str]]] = []
    current: list[str] = []
    path = ""

    def flush() -> None:
        if any(line.strip() for line in current):
            sections.append((path, current.copy()))
        current.clear()

    for line in markdown.splitlines():
        m = _HEADING.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            path = " > ".join(t for _, t in stack)
            current.append(line)
        elif _ARTICLE.match(line.strip()):
            flush()
            art = line.strip().strip("*")[:80]
            base = " > ".join(t for _, t in stack)
            path = f"{base} > {art}" if base else art
            current.append(line)
        else:
            current.append(line)
    flush()
    return [(p, "\n".join(lines).strip()) for p, lines in sections]


def _subdivide(text: str, cfg: ChunkerConfig) -> list[str]:
    if len(text) <= cfg.max_chars:
        return [text]
    parts: list[str] = []
    buf = ""
    for para in re.split(r"\n{2,}", text):
        if buf and len(buf) + len(para) + 2 > cfg.max_chars:
            parts.append(buf)
            tail = buf[-cfg.overlap_chars :] if cfg.overlap_chars else ""
            buf = f"{tail}\n\n{para}" if tail else para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
        while len(buf) > cfg.max_chars * 1.5:  # párrafo gigante sin saltos
            parts.append(buf[: cfg.max_chars])
            buf = buf[cfg.max_chars - cfg.overlap_chars :]
    if buf.strip():
        parts.append(buf)
    return parts


def chunk_document(
    doc: ParsedDocument,
    *,
    doc_id: str,
    authority: Authority,
    cfg: ChunkerConfig | None = None,
) -> list[Chunk]:
    cfg = cfg or ChunkerConfig()
    raw: list[tuple[str, str]] = []
    for path, text in _split_sections(doc.markdown) or [("", doc.markdown)]:
        for piece in _subdivide(text, cfg):
            raw.append((path, piece))

    # fusiona fragmentos diminutos con el anterior
    merged: list[tuple[str, str]] = []
    for path, text in raw:
        if merged and len(merged[-1][1]) < cfg.min_chars and (
            len(merged[-1][1]) + len(text) <= cfg.max_chars
        ):
            prev_path, prev_text = merged.pop()
            merged.append((prev_path or path, f"{prev_text}\n\n{text}"))
        else:
            merged.append((path, text))

    chunks: list[Chunk] = []
    for i, (path, text) in enumerate(merged):
        section = path or doc.title
        chunks.append(
            Chunk(
                id=sha256(f"{doc_id}:{i}:{text}")[:32],
                doc_id=doc_id,
                source_id=doc.source_id,
                url=doc.url,
                title=doc.title,
                text=text,
                context=f"{doc.title} — {section}",
                section=section,
                position=i,
                authority=authority,
                metadata=dict(doc.metadata),
                content_hash=sha256(text),
                updated_at=doc.fetched_at,
            )
        )
    return chunks
