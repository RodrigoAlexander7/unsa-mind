"""Dependencias FastAPI: acceso al Container, autenticación admin y rate limit."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from unsa_mind.config.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container


async def require_admin(request: Request, container: Container = Depends(get_container)) -> None:
    token = container.settings.admin_token
    if token is None:
        return
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip(), token):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token de administración inválido o ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )


class RateLimiter:
    """Ventana deslizante en memoria por IP (suficiente para una sola instancia)."""

    def __init__(self, limit: int = 20, window_s: float = 60.0) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> float | None:
        """None si se permite; si no, segundos hasta poder reintentar."""
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return self.window_s - (now - hits[0])
        hits.append(now)
        if len(self._hits) > 10_000:  # evita crecimiento sin límite
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window_s]:
                del self._hits[k]
        return None


async def rate_limit_chat(request: Request) -> None:
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    ip = request.client.host if request.client else "unknown"
    wait = limiter.check(ip)
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Demasiadas consultas; intenta de nuevo en unos instantes",
            headers={"Retry-After": str(int(wait) + 1)},
        )
