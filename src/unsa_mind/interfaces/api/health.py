from __future__ import annotations

from fastapi import APIRouter, Depends

from unsa_mind.config.container import Container
from unsa_mind.interfaces.api.deps import get_container
from unsa_mind.interfaces.api.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(c: Container = Depends(get_container)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        llm=c.llm.name,
        vector_chunks=await c.vector_store.count(),
        next_update=c.scheduler.next_run(),
    )
