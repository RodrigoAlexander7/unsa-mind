"""Utilidades compartidas por las interfaces (API, A2A, CLI). Sin dependencias de FastAPI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from unsa_mind.domain.entities import Answer, Schedule, SourceReport, UpdateReport


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def answer_payload(answer: Answer) -> dict[str, Any]:
    """Payload `final` del contrato de chat (también lo reutiliza A2A)."""
    return {
        "answer": answer.text,
        "citations": [
            {"title": c.title, "section": c.section, "url": c.url, "updated_at": iso(c.updated_at)}
            for c in answer.citations
        ],
        "abstained": answer.abstained,
        "intent": answer.intent.value,
        "data_as_of": iso(answer.data_as_of),
    }


def source_report_dict(r: SourceReport) -> dict[str, Any]:
    return {
        "source_id": r.source_id,
        "pages_fetched": r.pages_fetched,
        "documents_new": r.documents_new,
        "documents_changed": r.documents_changed,
        "documents_unchanged": r.documents_unchanged,
        "chunks_indexed": r.chunks_indexed,
        "chunks_deactivated": r.chunks_deactivated,
        "errors": list(r.errors),
    }


def update_report_dict(r: UpdateReport) -> dict[str, Any]:
    return {
        "started_at": iso(r.started_at),
        "finished_at": iso(r.finished_at),
        "ok": r.ok,
        "sources": [source_report_dict(s) for s in r.sources],
    }


def validate_cron(expr: str) -> None:
    """Lanza ValueError si `expr` no es un cron válido de 5 campos."""
    if len(expr.split()) != 5:
        raise ValueError("el cron debe tener 5 campos (min hora dia mes dia_semana)")
    from apscheduler.triggers.cron import CronTrigger

    CronTrigger.from_crontab(expr)


def next_fire(schedule: Schedule) -> str | None:
    """Próximo disparo teórico de un Schedule (ISO UTC); None si está deshabilitado."""
    if not schedule.enabled:
        return None
    now = datetime.now(timezone.utc)
    if schedule.cron:
        from apscheduler.triggers.cron import CronTrigger

        nxt = CronTrigger.from_crontab(schedule.cron).get_next_fire_time(None, now)
        return nxt.astimezone(timezone.utc).isoformat() if nxt else None
    from datetime import timedelta

    return (now + timedelta(minutes=schedule.interval_minutes)).isoformat()
