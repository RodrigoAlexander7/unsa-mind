from __future__ import annotations

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from unsa_mind.adapters.scheduling.apscheduler_scheduler import ApSchedulerAdapter, build_trigger
from unsa_mind.adapters.scheduling.factory import build_scheduler
from unsa_mind.config.settings import Settings
from unsa_mind.domain.entities import Schedule


async def _job() -> None:
    return None


def test_cron_has_priority_over_interval():
    t = build_trigger(Schedule(enabled=True, interval_minutes=10, cron="0 3 * * *"))
    assert isinstance(t, CronTrigger)


def test_interval_when_no_cron():
    t = build_trigger(Schedule(enabled=True, interval_minutes=15, cron=None))
    assert isinstance(t, IntervalTrigger)
    assert t.interval.total_seconds() == 900


@pytest.mark.parametrize("cron", ["not a cron", "* * * *", "61 * * * *", "0 3 * * * *"])
def test_invalid_cron_value_error(cron):
    with pytest.raises(ValueError, match="Cron inválido"):
        build_trigger(Schedule(cron=cron))


def test_invalid_interval():
    with pytest.raises(ValueError):
        build_trigger(Schedule(interval_minutes=0))


async def test_start_apply_hot_reschedule_and_pause():
    s = ApSchedulerAdapter()
    try:
        assert s.next_run() is None
        s.start(_job, Schedule(enabled=True, interval_minutes=60))
        first = s.next_run()
        assert first is not None
        s.apply(Schedule(enabled=True, interval_minutes=60, cron="30 4 * * *"))
        second = s.next_run()
        assert second is not None and "T04:30" in second
        s.apply(Schedule(enabled=False, interval_minutes=60))
        assert s.next_run() is None
        s.apply(Schedule(enabled=True, interval_minutes=5))
        assert s.next_run() is not None
        job = s._scheduler.get_job("update_cycle")
        assert job.max_instances == 1 and job.coalesce is True
    finally:
        s.shutdown()


async def test_start_disabled_is_paused():
    s = ApSchedulerAdapter()
    try:
        s.start(_job, Schedule(enabled=False))
        assert s.next_run() is None
    finally:
        s.shutdown()


async def test_apply_invalid_keeps_previous_schedule():
    s = ApSchedulerAdapter()
    try:
        s.start(_job, Schedule(enabled=True, interval_minutes=60))
        before = s.next_run()
        with pytest.raises(ValueError):
            s.apply(Schedule(cron="nope"))
        assert s.next_run() == before
    finally:
        s.shutdown()


def test_apply_before_start_and_shutdown_noop():
    s = ApSchedulerAdapter()
    s.apply(Schedule(cron="0 3 * * *"))
    s.shutdown()
    assert s.next_run() is None


def test_factory():
    assert isinstance(build_scheduler(Settings()), ApSchedulerAdapter)
