from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from gtg.models import (
    AppState,
    Config,
    CyclePosition,
    DayPlan,
    DayType,
    Exercise,
    MaxReps,
    PlannedSet,
    WindowConfig,
)
from gtg.notifier import Notifier
from gtg.scheduler import _SET_JOB_PREFIX, GTGScheduler
from gtg.storage import save_state

TZ = ZoneInfo("Europe/Prague")
TODAY = date.today()
TODAY_STR = TODAY.isoformat()


def make_config() -> Config:
    return Config(
        window=WindowConfig(start=time(8, 0), end=time(16, 0), max_extension_hours=2),
        min_gap_minutes=15,
        daily_reps_target_min=15,
        daily_reps_target_max=30,
        work_days=3,
        rest_days=1,
        recalibrate_after_cycles=2,
        snooze_options_minutes=[15, 30, 60],
        ntfy_base_url="https://ntfy.sh",
        ntfy_topic="gtg-test",
        exercises=[Exercise(id="oap", name="OAP", unit="reps")],
        timezone="Europe/Prague",
    )


def make_plan(n: int = 3, plan_date: str = TODAY_STR) -> DayPlan:
    base = datetime.now(TZ) + timedelta(hours=1)
    sets = [
        PlannedSet(
            index=i + 1,
            total=n,
            scheduled_at=base + timedelta(minutes=15 * i),
            reps={"oap": 3},
        )
        for i in range(n)
    ]
    return DayPlan(date=plan_date, day_type=DayType.MEDIUM, sets=sets)


def make_state(plan: DayPlan | None = None, cycle_number: int = 0) -> AppState:
    return AppState(
        max_reps=MaxReps(oap=6, ols=4, pullup=2),
        cycle_position=CyclePosition(cycle_number=cycle_number, day_in_cycle=2),
        today_plan=plan,
    )


@pytest.fixture
def sched_instance(tmp_path: Path) -> GTGScheduler:
    notifier = MagicMock(spec=Notifier)
    aps = BackgroundScheduler(timezone=TZ)
    aps.start()
    gtg = GTGScheduler(
        config=make_config(),
        state_path=tmp_path / "state.json",
        data_dir=tmp_path,
        notifier=notifier,
        tz=TZ,
        _scheduler=aps,
    )
    yield gtg
    aps.shutdown(wait=False)


def set_jobs(gtg: GTGScheduler) -> list:
    return [j for j in gtg._sched.get_jobs() if j.id.startswith(_SET_JOB_PREFIX)]


# ── _schedule_sets ─────────────────────────────────────────────────────────────


def test_schedule_sets_adds_future_jobs(sched_instance: GTGScheduler, tmp_path: Path) -> None:
    plan = make_plan(3)
    sched_instance._schedule_sets(plan)
    assert len(set_jobs(sched_instance)) == 3


def test_schedule_sets_skips_past_sets(sched_instance: GTGScheduler) -> None:
    now = datetime.now(TZ)
    past1 = now - timedelta(minutes=60)
    past2 = now - timedelta(minutes=10)
    future = now + timedelta(minutes=30)

    plan = DayPlan(
        date=TODAY_STR,
        day_type=DayType.MEDIUM,
        sets=[
            PlannedSet(index=1, total=3, scheduled_at=past1, reps={"oap": 3}),
            PlannedSet(index=2, total=3, scheduled_at=past2, reps={"oap": 3}),
            PlannedSet(index=3, total=3, scheduled_at=future, reps={"oap": 3}),
        ],
    )
    sched_instance._schedule_sets(plan)
    jobs = set_jobs(sched_instance)
    assert len(jobs) == 1  # jen budoucí set


# ── _cancel_set_jobs ───────────────────────────────────────────────────────────


def test_cancel_set_jobs_removes_all_set_jobs(sched_instance: GTGScheduler) -> None:
    sched_instance._schedule_sets(make_plan(3))
    assert len(set_jobs(sched_instance)) == 3
    sched_instance._cancel_set_jobs()
    assert len(set_jobs(sched_instance)) == 0


def test_cancel_set_jobs_leaves_other_jobs(sched_instance: GTGScheduler) -> None:
    from apscheduler.triggers.date import DateTrigger

    sched_instance._sched.add_job(
        lambda: None,
        trigger=DateTrigger(run_date=datetime.now(TZ) + timedelta(hours=1)),
        id="other_job",
    )
    sched_instance._schedule_sets(make_plan(2))
    sched_instance._cancel_set_jobs()
    remaining = [j.id for j in sched_instance._sched.get_jobs()]
    assert "other_job" in remaining


# ── reschedule / cancel_today ──────────────────────────────────────────────────


def test_reschedule_replaces_jobs(sched_instance: GTGScheduler) -> None:
    sched_instance._schedule_sets(make_plan(3))
    assert len(set_jobs(sched_instance)) == 3
    new_plan = make_plan(2)
    sched_instance.reschedule(new_plan)
    assert len(set_jobs(sched_instance)) == 2


def test_cancel_today_removes_all(sched_instance: GTGScheduler) -> None:
    sched_instance._schedule_sets(make_plan(4))
    sched_instance.cancel_today()
    assert len(set_jobs(sched_instance)) == 0


# ── _ensure_today_plan ─────────────────────────────────────────────────────────


def test_ensure_today_plan_noop_when_plan_is_current(
    sched_instance: GTGScheduler, tmp_path: Path
) -> None:
    state = make_state(plan=make_plan())
    save_state(state, sched_instance.state_path)
    sched_instance._ensure_today_plan()
    # Plán existuje pro dnešek — stav se nemění
    from gtg.storage import load_state

    loaded = load_state(sched_instance.state_path, TZ)
    assert loaded.today_plan.date == TODAY_STR


def test_ensure_today_plan_triggers_rollover_for_old_date(
    sched_instance: GTGScheduler, tmp_path: Path
) -> None:
    old_plan = make_plan(plan_date="2026-05-10")
    state = make_state(plan=old_plan)
    save_state(state, sched_instance.state_path)
    sched_instance._ensure_today_plan()

    from gtg.storage import load_state

    loaded = load_state(sched_instance.state_path, TZ)
    # Rollover proběhl → datum plánu se změnilo
    assert loaded.today_plan is None or loaded.today_plan.date == TODAY_STR


# ── _rollover ──────────────────────────────────────────────────────────────────


def test_rollover_advances_cycle(sched_instance: GTGScheduler, tmp_path: Path) -> None:
    state = make_state(plan=make_plan(), cycle_number=0)
    state.cycle_position = CyclePosition(cycle_number=0, day_in_cycle=2)
    save_state(state, sched_instance.state_path)
    sched_instance._rollover()

    from gtg.storage import load_state

    loaded = load_state(sched_instance.state_path, TZ)
    # day_in_cycle 2 → 3 → wrap → nový cyklus
    assert loaded.cycle_position.day_in_cycle == 3 or loaded.cycle_position.cycle_number == 1


def test_rollover_clears_completed_sets(sched_instance: GTGScheduler, tmp_path: Path) -> None:
    from gtg.models import CompletedSet

    state = make_state(plan=make_plan())
    state.completed_sets_today = [
        CompletedSet(
            index=1,
            total=3,
            scheduled_at=datetime(2026, 5, 13, 9, tzinfo=TZ),
            completed_at=datetime(2026, 5, 13, 9, 5, tzinfo=TZ),
            reps={"oap": 3},
            completed=True,
        )
    ]
    save_state(state, sched_instance.state_path)
    sched_instance._rollover()

    from gtg.storage import load_state

    loaded = load_state(sched_instance.state_path, TZ)
    assert loaded.completed_sets_today == []


def test_rollover_sends_calibration_when_due(sched_instance: GTGScheduler, tmp_path: Path) -> None:
    # recalibrate_after_cycles=2, last_calibration_cycle=0, cycle_number=1
    # po advance: cycle_number=2 → needs_recalibration = True
    state = make_state(cycle_number=1)
    state.cycle_position = CyclePosition(cycle_number=1, day_in_cycle=3)
    state.last_calibration_cycle = 0
    save_state(state, sched_instance.state_path)
    sched_instance._rollover()
    sched_instance.notifier.send_calibration_reminder.assert_called_once()


def test_rollover_no_calibration_when_not_due(sched_instance: GTGScheduler, tmp_path: Path) -> None:
    state = make_state(cycle_number=0)
    state.cycle_position = CyclePosition(cycle_number=0, day_in_cycle=2)
    state.last_calibration_cycle = 0
    save_state(state, sched_instance.state_path)
    sched_instance._rollover()
    sched_instance.notifier.send_calibration_reminder.assert_not_called()
