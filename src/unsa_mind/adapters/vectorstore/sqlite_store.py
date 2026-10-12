"""Vector store persistente en SQLite: vectores float32 en BLOB + FTS5 (BM25).

Búsqueda híbrida: top-k denso (coseno exacto, escaneo lineal de los chunks activos) y top-k
BM25 (FTS5, tokenizer unicode61 con remove_diacritics 2) fusionados con RRF. El score final se
normaliza a [0, 1] con la fórmula documentada en `_scoring.py`, de modo que consultas sin
relación obtienen scores bajos y el umbral `retrieval_min_score` es comparable entre consultas.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from array import array
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from unsa_mind.adapters.persistence._db import Database
from unsa_mind.adapters.memory import tokenize
from unsa_mind.domain.entities import Authority, Chunk, ScoredChunk

from ._scoring import (
    cosine,
    final_score,
    fts_query,
    lexical_fraction,
    metadata_matches,
    rrf_contribution,
)

MIGRATIONS = [
    """
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE chunks (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        url TEXT NOT NULL,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        context TEXT NOT NULL DEFAULT '',
        section TEXT NOT NULL DEFAULT '',
        position INTEGER NOT NULL DEFAULT 0,
        authority TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}',
        content_hash TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL,
        vector BLOB NOT NULL
    );
    CREATE INDEX idx_chunks_doc ON chunks(doc_id, active);
    CREATE VIRTUAL TABLE chunks_fts USING fts5(
        chunk_id UNINDEXED, content, tokenize = 'unicode61 remove_diacritics 2'
    );
    """,
]

DB_FILENAME = "vectors.db"


class VectorIndexMismatchError(RuntimeError):
    """El índice existente se creó con otra dimensión o modelo de embeddings."""


def pack(vector: Sequence[float]) -> bytes:
    a = array("f", vector)
    if sys.byteorder == "big":  # el formato en disco es siempre little-endian
        a.byteswap()
    return a.tobytes()


def unpack(blob: bytes) -> array:
    a = array("f")
    a.frombytes(blob)
    if sys.byteorder == "big":
        a.byteswap()
    return a


class SqliteVectorStore:
    def __init__(
        self,
        path: Path | str,
        dimension: int,
        *,
        embedder_id: str | None = None,
        dense_candidates: int | None = None,
    ) -> None:
        self.dimension = dimension
        self._dense_candidates = dense_candidates
        self._db = Database(path, MIGRATIONS)
        self._check_meta(embedder_id)

    # ---- metadatos / compatibilidad del índice ----
    def _check_meta(self, embedder_id: str | None) -> None:
        def fn(c: sqlite3.Connection) -> None:
            stored = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM meta")}
            if "dimension" in stored and int(stored["dimension"]) != self.dimension:
                raise VectorIndexMismatchError(
                    f"El índice vectorial fue creado con dimensión {stored['dimension']} pero el "
                    f"embedder actual produce {self.dimension}. Hay que reindexar: borra "
                    f"'{self._db.path}' y ejecuta de nuevo la actualización de fuentes."
                )
            old_id = stored.get("embedder_id")
            if embedder_id and old_id and old_id != embedder_id:
                raise VectorIndexMismatchError(
                    f"El índice vectorial fue creado con el embedder '{old_id}' pero el actual es "
                    f"'{embedder_id}'. Los vectores no son comparables: hay que reindexar "
                    f"(borra '{self._db.path}' y ejecuta de nuevo la actualización de fuentes)."
                )
            c.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('dimension', ?)",
                (str(self.dimension),),
            )
            if embedder_id:
                c.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('embedder_id', ?)",
                    (embedder_id,),
                )

        self._db.run_sync(fn, write=True)

    def _check_vector(self, vector: Sequence[float]) -> None:
        if len(vector) != self.dimension:
            raise VectorIndexMismatchError(
                f"Vector de dimensión {len(vector)} incompatible con el índice "
                f"({self.dimension}). Hay que reindexar si cambiaste de embedder."
            )

    # ---- API del puerto ----
    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks y vectors deben tener la misma longitud")
        for v in vectors:
            self._check_vector(v)
        rows = [
            (
                ch.id, ch.doc_id, ch.source_id, ch.url, ch.title, ch.text, ch.context, ch.section,
                ch.position, Authority(ch.authority).value,
                json.dumps(ch.metadata, ensure_ascii=False), ch.content_hash, int(ch.active),
                ch.updated_at.isoformat(), pack(v),
            )
            for ch, v in zip(chunks, vectors)
        ]
        fts_rows = [(ch.id, ch.indexable_text) for ch in chunks]

        def fn(c: sqlite3.Connection) -> None:
            c.executemany(
                """INSERT OR REPLACE INTO chunks(id,doc_id,source_id,url,title,text,context,
                       section,position,authority,metadata,content_hash,active,updated_at,vector)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            c.executemany("DELETE FROM chunks_fts WHERE chunk_id = ?", [(r[0],) for r in fts_rows])
            c.executemany("INSERT INTO chunks_fts(chunk_id, content) VALUES (?, ?)", fts_rows)

        await asyncio.to_thread(self._db.run_sync, fn, write=True)

    async def deactivate_document(self, doc_id: str) -> int:
        def fn(c: sqlite3.Connection) -> int:
            return c.execute(
                "UPDATE chunks SET active = 0 WHERE doc_id = ? AND active = 1", (doc_id,)
            ).rowcount

        return await asyncio.to_thread(self._db.run_sync, fn, write=True)

    async def count(self, *, active_only: bool = True) -> int:
        def fn(c: sqlite3.Connection) -> int:
            sql = "SELECT COUNT(*) FROM chunks" + (" WHERE active = 1" if active_only else "")
            return c.execute(sql).fetchone()[0]

        return await asyncio.to_thread(self._db.run_sync, fn, write=False)

    async def search(
        self,
        *,
        query_text: str,
        query_vector: Sequence[float],
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        self._check_vector(query_vector)
        q_vec = array("f", query_vector)

        def fn(c: sqlite3.Connection) -> list[ScoredChunk]:
            return self._search_sync(c, query_text, q_vec, k, filters)

        return await asyncio.to_thread(self._db.run_sync, fn, write=False)

    # ---- implementación ----
    def _search_sync(
        self,
        c: sqlite3.Connection,
        query_text: str,
        q_vec: array,
        k: int,
        filters: dict[str, Any] | None,
    ) -> list[ScoredChunk]:
        n_cand = self._dense_candidates or max(k, 20)
        dense_cos: dict[str, float] = {}
        for r in c.execute("SELECT id, metadata, vector FROM chunks WHERE active = 1"):
            if filters and not metadata_matches(json.loads(r["metadata"]), filters):
                continue
            dense_cos[r["id"]] = cosine(q_vec, unpack(r["vector"]))
        dense_rank = sorted(dense_cos, key=dense_cos.__getitem__, reverse=True)[:n_cand]

        bm25_rank: list[str] = []
        match = fts_query(query_text)
        if match:
            limit = n_cand if not filters else max(n_cand * 10, 200)
            for r in c.execute(
                """SELECT chunks_fts.chunk_id AS id, chunks.metadata AS metadata
                   FROM chunks_fts JOIN chunks ON chunks.id = chunks_fts.chunk_id
                   WHERE chunks_fts MATCH ? AND chunks.active = 1
                   ORDER BY bm25(chunks_fts) LIMIT ?""",
                (match, limit),
            ):
                if filters and not metadata_matches(json.loads(r["metadata"]), filters):
                    continue
                bm25_rank.append(r["id"])
            bm25_rank = bm25_rank[:n_cand]

        rrf: dict[str, float] = {}
        for ranking in (dense_rank, bm25_rank):
            for pos, cid in enumerate(ranking, start=1):
                rrf[cid] = rrf.get(cid, 0.0) + rrf_contribution(pos)
        if not rrf:
            return []

        ids = list(rrf)
        chunks = self._load_chunks(c, ids)
        q_tokens = set(tokenize(query_text))
        scored: list[ScoredChunk] = []
        for cid in ids:
            chunk = chunks.get(cid)
            if chunk is None:
                continue
            if cid in dense_cos:
                dense = dense_cos[cid]
            else:  # candidato solo léxico: calcula su coseno exacto
                row = c.execute("SELECT vector FROM chunks WHERE id = ?", (cid,)).fetchone()
                dense = cosine(q_vec, unpack(row["vector"]))
            lexical = lexical_fraction(q_tokens, chunk.indexable_text)
            scored.append(ScoredChunk(chunk, final_score(dense, lexical, rrf[cid])))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]

    @staticmethod
    def _load_chunks(c: sqlite3.Connection, ids: list[str]) -> dict[str, Chunk]:
        out: dict[str, Chunk] = {}
        for i in range(0, len(ids), 500):
            part = ids[i : i + 500]
            marks = ",".join("?" * len(part))
            for r in c.execute(f"SELECT * FROM chunks WHERE id IN ({marks})", part):
                out[r["id"]] = Chunk(
                    id=r["id"],
                    doc_id=r["doc_id"],
                    source_id=r["source_id"],
                    url=r["url"],
                    title=r["title"],
                    text=r["text"],
                    context=r["context"],
                    section=r["section"],
                    position=r["position"],
                    authority=Authority(r["authority"]),
                    metadata=json.loads(r["metadata"]),
                    content_hash=r["content_hash"],
                    active=bool(r["active"]),
                    updated_at=datetime.fromisoformat(r["updated_at"]),
                )
        return out
