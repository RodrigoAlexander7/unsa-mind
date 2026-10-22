"""Administración: schedule en caliente, fuentes, actualizaciones, reportes y estadísticas."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Response
from fastapi.responses import JSONResponse

from unsa_mind.config.container import Container
from unsa_mind.domain.entities import Authority, DocumentRecord, Schedule
from unsa_mind.interfaces.api.deps import get_container, require_admin
from unsa_mind.interfaces.api.schemas import (
    ChunkOut,
    DocumentChunks,
    DocumentOut,
    DocumentPage,
    ScheduleIn,
    ScheduleOut,
    SourceIn,
    SourceOut,
    StatsOut,
    UpdateRequest,
)
from unsa_mind.interfaces.common import iso, update_report_dict

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


def _doc_out(d: DocumentRecord) -> DocumentOut:
    return DocumentOut(
        doc_id=d.doc_id,
        source_id=d.source_id,
        url=d.url,
        title=d.title,
        version=d.version,
        content_hash=d.content_hash,
        fetched_at=iso(d.fetched_at),
        active=d.active,
    )


@router.get("/documents", response_model=DocumentPage)
async def list_documents(
    source_id: str | None = None,
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
    c: Container = Depends(get_container),
) -> DocumentPage:
    """Solo lectura: documentos indexados (más recientes primero)."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    docs = [
        d
        for d in await c.documents.list_documents(active_only=active_only)
        if source_id is None or d.source_id == source_id
    ]
    docs.sort(key=lambda d: d.fetched_at, reverse=True)
    return DocumentPage(
        total=len(docs),
        limit=limit,
        offset=offset,
        items=[_doc_out(d) for d in docs[offset : offset + limit]],
    )


@router.get("/documents/{doc_id}/chunks", response_model=DocumentChunks)
async def document_chunks(doc_id: str, c: Container = Depends(get_container)) -> DocumentChunks:
    """Solo lectura: el texto indexado (chunks) de un documento, en orden."""
    doc = next((d for d in await c.documents.list_documents(active_only=False) if d.doc_id == doc_id), None)
    if doc is None:
        raise HTTPException(404, f"Documento '{doc_id}' no encontrado")
    chunks = await c.vector_store.list_chunks(doc_id)
    return DocumentChunks(
        document=_doc_out(doc),
        chunks=[
            ChunkOut(
                id=ch.id,
                position=ch.position,
                section=ch.section,
                text=ch.text,
                context=ch.context,
                authority=Authority(ch.authority).value,
                metadata=ch.metadata,
                active=ch.active,
                updated_at=iso(ch.updated_at),
            )
            for ch in chunks
        ],
    )


@router.get("/stats", response_model=StatsOut)
async def stats(c: Container = Depends(get_container)) -> StatsOut:
    return StatsOut(
        chunks_active=await c.vector_store.count(),
        documents_active=len(await c.documents.list_documents(active_only=True)),
        sources=len(await c.sources.list_sources()),
    )
