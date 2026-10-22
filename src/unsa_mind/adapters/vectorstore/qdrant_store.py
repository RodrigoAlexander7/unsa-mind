
"""Vector store Qdrant (opcional: `pip install unsa-mind[qdrant]`).

Colección con vector denso (coseno) + vector sparse "bm25" (TF por token con modificador IDF
del servidor, equivalente a BM25 sin normalización de longitud). Se consultan ambos por
separado y se fusionan con RRF en cliente para aplicar el MISMO score normalizado [0, 1] que
SqliteVectorStore (ver `_scoring.py`).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from unsa_mind.adapters.memory import tokenize
from unsa_mind.domain.entities import Authority, Chunk, ScoredChunk

from ._scoring import cosine, final_score, lexical_fraction, rrf_contribution

_NAMESPACE = uuid.UUID("6f1c7e0e-3b3e-4c52-9a52-5a1c0f6d7a11")
_DENSE = "dense"
_SPARSE = "bm25"
_SPARSE_SPACE = 2**31 - 1


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, chunk_id))


def sparse_vector(text: str) -> tuple[list[int], list[float]]:
    counts = Counter(
        int(hashlib.md5(t.encode()).hexdigest()[:8], 16) % _SPARSE_SPACE for t in tokenize(text)
    )
    return list(counts), [float(v) for v in counts.values()]


def _import_qdrant():
    try:
        import qdrant_client
        from qdrant_client import models
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise RuntimeError(
            "QdrantVectorStore requiere 'qdrant-client'. Instálalo con: "
            "pip install 'unsa-mind[qdrant]'"
        ) from exc
    return qdrant_client, models


class QdrantVectorStore:
    def __init__(
        self,
        dimension: int,
        *,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        collection: str = "unsa_chunks",
        client: Any = None,
    ) -> None:
        qdrant_client, models = _import_qdrant()
        self._m = models
        self.dimension = dimension
        self.collection = collection
        if client is not None:
            self._client = client
        elif url == ":memory:":
            self._client = qdrant_client.AsyncQdrantClient(":memory:")
        else:
            self._client = qdrant_client.AsyncQdrantClient(url=url, api_key=api_key)
        self._ready = False

    async def _ensure(self) -> None:
        if self._ready:
            return
        m = self._m
        if not await self._client.collection_exists(self.collection):
            await self._client.create_collection(
                self.collection,
                vectors_config={
                    _DENSE: m.VectorParams(size=self.dimension, distance=m.Distance.COSINE)
                },
                sparse_vectors_config={_SPARSE: m.SparseVectorParams(modifier=m.Modifier.IDF)},
            )
            for name in ("active", "doc_id"):
                await self._client.create_payload_index(
                    self.collection, name, m.PayloadSchemaType.BOOL if name == "active"
                    else m.PayloadSchemaType.KEYWORD
                )
        else:
            info = await self._client.get_collection(self.collection)
            vectors = info.config.params.vectors
            size = vectors[_DENSE].size if isinstance(vectors, dict) else vectors.size
            if size != self.dimension:
                raise RuntimeError(
                    f"La colección Qdrant '{self.collection}' tiene dimensión {size} pero el "
                    f"embedder produce {self.dimension}. Hay que reindexar: elimina la colección "
                    "y vuelve a ejecutar la actualización de fuentes."
                )
        self._ready = True

    def _filter(self, filters: dict[str, Any] | None, *, active: bool = True):
        m = self._m
        must = [m.FieldCondition(key="active", match=m.MatchValue(value=True))] if active else []
        for key, value in (filters or {}).items():
            must.append(m.FieldCondition(key=f"metadata.{key}", match=m.MatchValue(value=value)))
        return m.Filter(must=must)

    @staticmethod
    def _payload(ch: Chunk) -> dict[str, Any]:
        return {
            "chunk_id": ch.id, "doc_id": ch.doc_id, "source_id": ch.source_id, "url": ch.url,
            "title": ch.title, "text": ch.text, "context": ch.context, "section": ch.section,
            "position": ch.position, "authority": Authority(ch.authority).value,
            "metadata": json.loads(json.dumps(ch.metadata, default=str)),
            "content_hash": ch.content_hash, "active": ch.active,
            "updated_at": ch.updated_at.isoformat(),
        }

    @staticmethod
    def _chunk(p: dict[str, Any]) -> Chunk:
        return Chunk(
            id=p["chunk_id"], doc_id=p["doc_id"], source_id=p["source_id"], url=p["url"],
            title=p["title"], text=p["text"], context=p.get("context", ""),
            section=p.get("section", ""), position=p.get("position", 0),
            authority=Authority(p["authority"]), metadata=p.get("metadata", {}),
            content_hash=p.get("content_hash", ""), active=p.get("active", True),
            updated_at=datetime.fromisoformat(p["updated_at"]),
        )

    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks y vectors deben tener la misma longitud")
        await self._ensure()
        m = self._m
        points = []
        for ch, vec in zip(chunks, vectors):
            if len(vec) != self.dimension:
                raise RuntimeError(
                    f"Vector de dimensión {len(vec)} incompatible con la colección "
                    f"({self.dimension}). Hay que reindexar si cambiaste de embedder."
                )
            idx, vals = sparse_vector(ch.indexable_text)
            points.append(
                m.PointStruct(
                    id=point_id(ch.id),
                    vector={
                        _DENSE: list(vec),
                        _SPARSE: m.SparseVector(indices=idx, values=vals),
                    },
                    payload=self._payload(ch),
                )
            )
        for i in range(0, len(points), 128):
            await self._client.upsert(self.collection, points=points[i : i + 128], wait=True)

    async def deactivate_document(self, doc_id: str) -> int:
        await self._ensure()
        m = self._m
        flt = m.Filter(
            must=[
                m.FieldCondition(key="doc_id", match=m.MatchValue(value=doc_id)),
                m.FieldCondition(key="active", match=m.MatchValue(value=True)),
            ]
        )
        n = (await self._client.count(self.collection, count_filter=flt, exact=True)).count
        if n:
            await self._client.set_payload(
                self.collection, payload={"active": False}, points=flt, wait=True
            )
        return n

    async def list_chunks(self, doc_id: str) -> list[Chunk]:
        await self._ensure()
        m = self._m
        flt = m.Filter(must=[m.FieldCondition(key="doc_id", match=m.MatchValue(value=doc_id))])
        out: list[Chunk] = []
        offset = None
        while True:
            points, offset = await self._client.scroll(
                self.collection, scroll_filter=flt, limit=256, offset=offset, with_payload=True
            )
            out.extend(self._chunk(p.payload) for p in points)
            if offset is None:
                break
        return sorted(out, key=lambda ch: ch.position)

    async def count(self, *, active_only: bool = True) -> int:
        await self._ensure()
        flt = self._filter(None) if active_only else None
        return (await self._client.count(self.collection, count_filter=flt, exact=True)).count

    async def search(
        self,
        *,
        query_text: str,
        query_vector: Sequence[float],
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        await self._ensure()
        m = self._m
        flt = self._filter(filters)
        n_cand = max(k, 20)
        dense = await self._client.query_points(
            self.collection, query=list(query_vector), using=_DENSE, query_filter=flt,
            limit=n_cand, with_payload=True, with_vectors=[_DENSE],
        )
        sparse_hits = []
        idx, vals = sparse_vector(query_text)
        if idx:
            sparse_hits = (
                await self._client.query_points(
                    self.collection,
                    query=m.SparseVector(indices=idx, values=[1.0] * len(idx)),
                    using=_SPARSE, query_filter=flt, limit=n_cand,
                    with_payload=True, with_vectors=[_DENSE],
                )
            ).points

        rrf: dict[str, float] = {}
        cands: dict[str, Any] = {}
        for hits in (dense.points, sparse_hits):
            for rank, hit in enumerate(hits, start=1):
                rrf[hit.payload["chunk_id"]] = rrf.get(hit.payload["chunk_id"], 0.0) + (
                    rrf_contribution(rank)
                )
                cands[hit.payload["chunk_id"]] = hit
        q_tokens = set(tokenize(query_text))
        scored = []
        for cid, hit in cands.items():
            chunk = self._chunk(hit.payload)
            vec = hit.vector[_DENSE] if isinstance(hit.vector, dict) else hit.vector
            scored.append(
                ScoredChunk(
                    chunk,
                    final_score(
                        cosine(query_vector, vec),
                        lexical_fraction(q_tokens, chunk.indexable_text),
                        rrf[cid],
                    ),
                )
            )
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]
