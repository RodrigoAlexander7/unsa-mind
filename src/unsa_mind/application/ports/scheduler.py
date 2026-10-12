from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from unsa_mind.domain.entities import Schedule


class SchedulerPort(Protocol):
    """Dispara `job` según el Schedule. `apply` se puede llamar en caliente."""

    def start(self, job: Callable[[], Awaitable[None]], schedule: Schedule) -> None: ...

    def apply(self, schedule: Schedule) -> None: ...

    def shutdown(self) -> None: ...

    def next_run(self) -> str | None: ...
