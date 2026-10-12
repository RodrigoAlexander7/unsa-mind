"""Fusión híbrida y normalización de score, compartida por los almacenes persistentes.

Fórmula (documentada porque el umbral `retrieval_min_score` depende de ella):

    dense    = max(0, cos(q, d))                       coseno absoluto, en [0, 1]
    lexical  = |tokens(q) ∩ tokens(d)| / |tokens(q)|   fracción de términos de la consulta presentes
    quality  = 0.5 * dense + 0.5 * lexical             (misma base que InMemoryVectorStore)
    rrf_norm = Σ_listas 1/(60 + rank) / (2 / 61)       RRF normalizado: 1.0 = primero en ambas listas
    score    = quality * (0.8 + 0.2 * rrf_norm)        en [0, 1]

El RRF decide el orden relativo entre listas (densa y BM25) pero NO eleva por sí solo el score:
una consulta sin relación es primera en su lista densa por definición, así que su `quality`
(coseno bajo, 0 términos presentes) mantiene el score bajo y comparable entre consultas.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from unsa_mind.adapters.memory import tokenize

RRF_K = 60
_RRF_MAX = 2.0 / (RRF_K + 1)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def lexical_fraction(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & set(tokenize(text))) / len(query_tokens)


def rrf_contribution(rank: int) -> float:
    """`rank` empieza en 1."""
    return 1.0 / (RRF_K + rank)


def final_score(dense_cos: float, lexical: float, rrf: float) -> float:
    quality = 0.5 * max(0.0, min(1.0, dense_cos)) + 0.5 * max(0.0, min(1.0, lexical))
    rrf_norm = min(1.0, rrf / _RRF_MAX)
    return max(0.0, min(1.0, quality * (0.8 + 0.2 * rrf_norm)))


def fts_query(query_text: str) -> str | None:
    """Tokens entre comillas unidos por OR (seguro frente a la sintaxis de FTS5)."""
    tokens = list(dict.fromkeys(tokenize(query_text)))
    if not tokens:
        return None
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)


def metadata_matches(metadata: dict, filters: dict | None) -> bool:
    """Igualdad por clave, igual que InMemoryVectorStore."""
    return not filters or all(metadata.get(k) == v for k, v in filters.items())
