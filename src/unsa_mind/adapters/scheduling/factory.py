from __future__ import annotations

from unsa_mind.adapters.scheduling.apscheduler_scheduler import ApSchedulerAdapter
from unsa_mind.application.ports.scheduler import SchedulerPort
from unsa_mind.config.settings import Settings


def build_scheduler(settings: Settings) -> SchedulerPort:
    return ApSchedulerAdapter()
