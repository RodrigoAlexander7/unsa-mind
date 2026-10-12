"""Router de intención heurístico (barato y determinista). Sustituible por un LLM pequeño."""

from __future__ import annotations

import re
import unicodedata

from unsa_mind.domain.entities import Intent


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


_RULES: list[tuple[Intent, re.Pattern[str]]] = [
    (Intent.GRADUATE, re.compile(r"posgrado|maestria|doctorado|segunda especialidad")),
    (Intent.AGREEMENTS, re.compile(r"convenio|movilidad|beca|intercambio|pasantia|cooperacion")),
    (
        Intent.ADMISSION,
        re.compile(r"admision|ingres|postul|vacante|cepru|prospecto|temario"),
    ),
    (
        Intent.PROCEDURES,
        re.compile(
            r"constancia|reserva de matricula|convalidaci|justific|inasisten|tramite|matricul|"
            r"certificado|traslado|retiro|licencia|examen"
        ),
    ),
]
_OUT = re.compile(r"\b(receta|futbol|clima|bitcoin|politica|chiste|pelicula)\b")


def classify_intent(question: str) -> Intent:
    q = _norm(question)
    if _OUT.search(q):
        return Intent.OUT_OF_SCOPE
    for intent, pat in _RULES:
        if pat.search(q):
            return intent
    return Intent.GENERAL
