"""Scheduler embebido con APScheduler 3.x (reprogramable en caliente)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from unsa_mind.domain.entities import Schedule

JOB_ID = "update_cycle"


def build_trigger(schedule: Schedule) -> BaseTrigger:
    """`cron` (5 campos) tiene prioridad sobre `interval_minutes`."""
    if schedule.cron and schedule.cron.strip():
        expr = schedule.cron.strip()
        if len(expr.split()) != 5:
            raise ValueError(f"Cron inválido '{expr}': se esperan 5 campos (min hora día mes díasemana)")
        try:
            return CronTrigger.from_crontab(expr)
        except ValueError as exc:
            raise ValueError(f"Cron inválido '{expr}': {exc}") from exc
    if schedule.interval_minutes is None or schedule.interval_minutes < 1:
        raise ValueError(f"interval_minutes debe ser >= 1 (recibido {schedule.interval_minutes})")
    return IntervalTrigger(minutes=schedule.interval_minutes)


class ApSchedulerAdapter:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._job: Callable[[], Awaitable[None]] | None = None
        self._schedule: Schedule | None = None

    def start(self, job: Callable[[], Awaitable[None]], schedule: Schedule) -> None:
        trigger = build_trigger(schedule)  # valida antes de arrancar
        self._job = job
        self._schedule = schedule
        self._scheduler.add_job(
            job,
            trigger,
            id=JOB_ID,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            misfire_grace_time=300,
        )
        if not self._scheduler.running:
            self._scheduler.start()
        if not schedule.enabled:
            self._scheduler.pause_job(JOB_ID)

    def apply(self, schedule: Schedule) -> None:
        trigger = build_trigger(schedule)
        self._schedule = schedule
        if self._job is None or self._scheduler.get_job(JOB_ID) is None:
            return  # aún no iniciado
        self._scheduler.reschedule_job(JOB_ID, trigger=trigger)
        if schedule.enabled:
            self._scheduler.resume_job(JOB_ID)
        else:
            self._scheduler.pause_job(JOB_ID)

    def next_run(self) -> str | None:
        job = self._scheduler.get_job(JOB_ID)
        nxt = getattr(job, "next_run_time", None) if job else None
        return nxt.isoformat() if nxt else None

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
