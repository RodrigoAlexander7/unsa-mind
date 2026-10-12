"""Administración: schedule en caliente, fuentes, actualizaciones, reportes y estadísticas."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Response
from fastapi.responses import JSONResponse

from unsa_mind.config.container import Container
from unsa_mind.domain.entities import Schedule
from unsa_mind.interfaces.api.deps import get_container, require_admin
from unsa_mind.interfaces.api.schemas import (
    ScheduleIn,
    ScheduleOut,
    SourceIn,
    SourceOut,
    StatsOut,
    UpdateRequest,
)
from unsa_mind.interfaces.common import update_report_dict

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _sched_out(s: Schedule, c: Container) -> ScheduleOut:
    return ScheduleOut(
        enabled=s.enabled,
        interval_minutes=s.interval_minutes,
        cron=s.cron,
        next_run=c.scheduler.next_run(),
    )


@router.get("/schedule", response_model=ScheduleOut)
async def get_schedule(c: Container = Depends(get_container)) -> ScheduleOut:
    return _sched_out(await c.settings_repo.get_schedule(), c)


@router.put("/schedule", response_model=ScheduleOut)
async def put_schedule(body: ScheduleIn, c: Container = Depends(get_container)) -> ScheduleOut:
    schedule = Schedule(body.enabled, body.interval_minutes, body.cron)
    await c.settings_repo.save_schedule(schedule)
    c.scheduler.apply(schedule)  # en caliente, sin reiniciar
    return _sched_out(schedule, c)


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(c: Container = Depends(get_container)) -> list[SourceOut]:
    return [SourceOut.from_entity(s) for s in await c.sources.list_sources()]


@router.post("/sources", response_model=SourceOut, status_code=201)
async def create_source(body: SourceIn, c: Container = Depends(get_container)) -> SourceOut:
    if await c.sources.get_source(body.id):
        raise HTTPException(409, f"Ya existe la fuente '{body.id}'")
    entity = body.to_entity()
    await c.sources.save_source(entity)
    return SourceOut.from_entity(entity)


@router.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(source_id: str, c: Container = Depends(get_container)) -> SourceOut:
    s = await c.sources.get_source(source_id)
    if not s:
        raise HTTPException(404, f"Fuente '{source_id}' no encontrada")
    return SourceOut.from_entity(s)


@router.put("/sources/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: str, body: SourceIn, c: Container = Depends(get_container)
) -> SourceOut:
    current = await c.sources.get_source(source_id)
    if not current:
        raise HTTPException(404, f"Fuente '{source_id}' no encontrada")
    if body.id != source_id:
        raise HTTPException(422, "El id del cuerpo no coincide con el de la ruta")
    entity = body.to_entity(last_run_at=current.last_run_at)
    await c.sources.save_source(entity)
    return SourceOut.from_entity(entity)


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: str, c: Container = Depends(get_container)) -> Response:
    if not await c.sources.get_source(source_id):
        raise HTTPException(404, f"Fuente '{source_id}' no encontrada")
    await c.sources.delete_source(source_id)
    return Response(status_code=204)


@router.post("/update")
async def trigger_update(
    background: BackgroundTasks,
    body: UpdateRequest | None = Body(default=None),
    wait: bool = False,
    c: Container = Depends(get_container),
) -> JSONResponse:
    req = body or UpdateRequest()
    if wait:
        report = await c.update_cycle.execute(force=req.force, only=req.only)
        return JSONResponse(update_report_dict(report), status_code=200)
    background.add_task(c.update_cycle.execute, force=req.force, only=req.only)
    return JSONResponse({"status": "accepted"}, status_code=202, background=background)


@router.get("/reports")
async def reports(limit: int = 20, c: Container = Depends(get_container)) -> list[dict]:
    limit = max(1, min(limit, 200))
    return [update_report_dict(r) for r in await c.settings_repo.list_reports(limit)]


@router.get("/stats", response_model=StatsOut)
async def stats(c: Container = Depends(get_container)) -> StatsOut:
    return StatsOut(
        chunks_active=await c.vector_store.count(),
        documents_active=len(await c.documents.list_documents(active_only=True)),
        sources=len(await c.sources.list_sources()),
    )
