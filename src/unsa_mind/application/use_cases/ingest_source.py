"""Caso de uso: rastrear una fuente e indexar solo lo que cambió (idempotente por hash)."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from collections.abc import Sequence
from urllib.parse import urldefrag

from unsa_mind.application.ports import (
    DocumentRepositoryPort,
    EmbedderPort,
    FetcherPort,
    ParserPort,
    VectorStorePort,
)
from unsa_mind.application.services.chunker import ChunkerConfig, chunk_document
from unsa_mind.domain.entities import (
    DIRECTORY_CONTENT_TYPE,
    DocumentRecord,
    RawDocument,
    Source,
    SourceReport,
    sha256,
)
from unsa_mind.domain.errors import ParseError

log = logging.getLogger(__name__)
_EMBED_BATCH = 64


class IngestSource:
    def __init__(
        self,
        *,
        fetcher: FetcherPort,
        parsers: Sequence[ParserPort],
        embedder: EmbedderPort,
        vector_store: VectorStorePort,
        documents: DocumentRepositoryPort,
        chunker_config: ChunkerConfig | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._parsers = list(parsers)
        self._embedder = embedder
        self._store = vector_store
        self._documents = documents
        self._chunker_cfg = chunker_config or ChunkerConfig()

    def _parser_for(self, content_type: str) -> ParserPort:
        for parser in self._parsers:
            if parser.supports(content_type):
                return parser
        raise ParseError(f"Sin parser para content-type '{content_type}'")

    async def execute(self, source: Source) -> SourceReport:
        report = SourceReport(source_id=source.id)
        queue: deque[str] = deque([source.url])
        seen: set[str] = set()
        link_re = re.compile(source.link_pattern) if source.link_pattern else None

        while queue and report.pages_fetched < source.max_pages:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            try:
                raw = await self._fetcher.fetch(url, source_id=source.id)
                report.pages_fetched += 1
                is_dir = raw.content_type == DIRECTORY_CONTENT_TYPE
                if not is_dir:
                    await self._process(raw, source, report)
                if source.follow_links or is_dir:  # una carpeta local siempre se recorre
                    for link in raw.links:
                        link = urldefrag(link)[0]
                        if link not in seen and (link_re is None or link_re.search(link)):
                            queue.append(link)
            except Exception as exc:  # una página caída no debe abortar la fuente
                log.warning("Error en %s: %s", url, exc)
                report.errors.append(f"{url}: {exc}")
        return report

    async def _process(self, raw: RawDocument, source: Source, report: SourceReport) -> None:
        parser = self._parser_for(raw.content_type)
        log.info("[%s] leyendo %s", source.id, raw.url)
        # En un hilo: el OCR puede tardar minutos y no debe bloquear el servidor
        parsed = await asyncio.to_thread(parser.parse, raw, base_metadata=dict(source.metadata))
        if not parsed.markdown.strip():
            raise ParseError("documento sin contenido textual")

        previous = await self._documents.get_active(raw.url)
        if previous and previous.content_hash == parsed.content_hash:
            report.documents_unchanged += 1
            log.info("[%s] sin cambios: %s", source.id, raw.url)
            return

        version = previous.version + 1 if previous else 1
        doc_id = f"{sha256(raw.url)[:16]}-v{version}"
        chunks = chunk_document(
            parsed, doc_id=doc_id, authority=source.authority, cfg=self._chunker_cfg
        )
        vectors: list[list[float]] = []
        texts = [c.indexable_text for c in chunks]
        for i in range(0, len(texts), _EMBED_BATCH):
            log.info("[%s] embeddings %d/%d: %s", source.id, min(i + _EMBED_BATCH, len(texts)), len(texts), raw.url)
            vectors.extend(await self._embedder.embed_documents(texts[i : i + _EMBED_BATCH]))

        await self._store.upsert(chunks, vectors)
        if previous:  # la versión anterior se conserva como inactiva (auditoría)
            report.chunks_deactivated += await self._store.deactivate_document(previous.doc_id)
            await self._documents.deactivate(previous.doc_id)
            report.documents_changed += 1
        else:
            report.documents_new += 1
        report.chunks_indexed += len(chunks)
        await self._documents.save(
            DocumentRecord(
                doc_id=doc_id,
                source_id=source.id,
                url=raw.url,
                title=parsed.title,
                content_hash=parsed.content_hash,
                version=version,
                fetched_at=parsed.fetched_at,
            )
        )
