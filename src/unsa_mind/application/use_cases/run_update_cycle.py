"""Caso de uso: ciclo de actualización (lo dispara el scheduler, la API o la CLI)."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from unsa_mind.application.ports import SettingsRepositoryPort, SourceRepositoryPort
from unsa_mind.application.use_cases.ingest_source import IngestSource
from unsa_mind.domain.entities import Source, SourceReport, UpdateReport, utcnow

log = logging.getLogger(__name__)


class RunUpdateCycle:
    """Ejecuta la ingesta de las fuentes que corresponda.

    - Fuentes sin `interval_minutes` propio: se ejecutan en cada disparo del scheduler
      (cuya cadencia es el `Schedule` global, modificable en caliente).
    - Fuentes con `interval_minutes`: solo si ya transcurrió ese intervalo (p. ej. avisos
      diarios vs. reglamentos semanales).
    - `force=True` ignora los intervalos propios.
    """

    def __init__(
        self,
        *,
        sources: SourceRepositoryPort,
        settings: SettingsRepositoryPort,
        ingest: IngestSource,
        concurrency: int = 3,
    ) -> None:
        self._sources = sources
        self._settings = settings
        self._ingest = ingest
        self._sem = asyncio.Semaphore(concurrency)
        self._lock = asyncio.Lock()  # evita ciclos solapados

    @staticmethod
    def _is_due(source: Source, force: bool) -> bool:
        if force or source.interval_minutes is None or source.last_run_at is None:
            return True
        return utcnow() - source.last_run_at >= timedelta(minutes=source.interval_minutes)

    async def execute(
        self, *, force: bool = False, only: list[str] | None = None
    ) -> UpdateReport:
        report = UpdateReport(started_at=utcnow())
        if self._lock.locked():
            log.info("Ciclo de actualización ya en curso; se omite")
            report.finished_at = utcnow()
            return report
        async with self._lock:
            candidates = [
                s
                for s in await self._sources.list_sources(enabled_only=True)
                if (only is None or s.id in only) and self._is_due(s, force or bool(only))
            ]

            async def run(source: Source) -> SourceReport:
                async with self._sem:
                    try:
                        result = await self._ingest.execute(source)
                    except Exception as exc:
                        result = SourceReport(source_id=source.id, errors=[str(exc)])
                    source.last_run_at = utcnow()
                    await self._sources.save_source(source)
                    return result

            report.sources = list(await asyncio.gather(*(run(s) for s in candidates)))
            report.finished_at = utcnow()
            await self._settings.save_report(report)
            return report
