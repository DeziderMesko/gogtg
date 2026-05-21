import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

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
from gtg.scheduling import (
    advance_cycle,
    base_sets,
    day_type_for_position,
    nearest_past_uncompleted,
    needs_recalibration,
    plan_day,
    reschedule_remaining,
    set_reps,
    sets_for_day,
)

TZ = ZoneInfo("Europe/Prague")


@pytest.fixture
def config() -> Config:
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
        ntfy_topic="test",
        exercises=[
            Exercise(id="oap", name="OAP", unit="reps"),
            Exercise(id="ols", name="OLS", unit="reps"),
            Exercise(id="pullup", name="Shyb", unit="reps"),
        ],
        timezone="Europe/Prague",
    )


@pytest.fixture
def max_reps() -> MaxReps:
    return MaxReps(oap=6, ols=6, pullup=6)


class TestDayTypeForPosition:
    def test_full_cycle_order(self, config):
        expected = [DayType.LIGHT, DayType.HEAVY, DayType.MEDIUM, DayType.REST]
        for i, expected_type in enumerate(expected):
            pos = CyclePosition(cycle_number=0, day_in_cycle=i)
            assert day_type_for_position(pos, config) == expected_type

    def test_new_cycle_starts_with_light(self, config):
        pos = CyclePosition(cycle_number=3, day_in_cycle=0)
        assert day_type_for_position(pos, config) == DayType.LIGHT

    def test_rest_day_is_last(self, config):
        pos = CyclePosition(cycle_number=0, day_in_cycle=3)
        assert day_type_for_position(pos, config) == DayType.REST


class TestAdvanceCycle:
    def test_advance_within_cycle(self, config):
        pos = CyclePosition(cycle_number=0, day_in_cycle=0)
        assert advance_cycle(pos, config) == CyclePosition(cycle_number=0, day_in_cycle=1)

    def test_wrap_resets_day(self, config):
        pos = CyclePosition(cycle_number=0, day_in_cycle=3)
        result = advance_cycle(pos, config)
        assert result == CyclePosition(cycle_number=1, day_in_cycle=0)

    def test_cycle_number_increments_on_wrap(self, config):
        pos = CyclePosition(cycle_number=5, day_in_cycle=3)
        assert advance_cycle(pos, config).cycle_number == 6


class TestNeedsRecalibration:
    def test_no_recalibration_initially(self, config, max_reps):
        state = AppState(
            max_reps=max_reps,
            cycle_position=CyclePosition(cycle_number=0, day_in_cycle=0),
            today_plan=None,
            last_calibration_cycle=0,
        )
        assert not needs_recalibration(state, config)

    def test_no_recalibration_after_one_cycle(self, config, max_reps):
        state = AppState(
            max_reps=max_reps,
            cycle_position=CyclePosition(cycle_number=1, day_in_cycle=0),
            today_plan=None,
            last_calibration_cycle=0,
        )
        assert not needs_recalibration(state, config)

    def test_recalibration_after_two_cycles(self, config, max_reps):
        state = AppState(
            max_reps=max_reps,
            cycle_position=CyclePosition(cycle_number=2, day_in_cycle=0),
            today_plan=None,
            last_calibration_cycle=0,
        )
        assert needs_recalibration(state, config)

    def test_no_recalibration_after_reset(self, config, max_reps):
        state = AppState(
            max_reps=max_reps,
            cycle_position=CyclePosition(cycle_number=4, day_in_cycle=0),
            today_plan=None,
            last_calibration_cycle=3,
        )
        assert not needs_recalibration(state, config)


class TestSetReps:
    def test_floor_half(self):
        assert set_reps(MaxReps(oap=6, ols=5, pullup=4)) == {"oap": 3, "ols": 2, "pullup": 2}

    def test_odd_max_floors(self):
        assert set_reps(MaxReps(oap=7, ols=7, pullup=7)) == {"oap": 3, "ols": 3, "pullup": 3}

    def test_one_max_gives_zero(self):
        assert set_reps(MaxReps(oap=1, ols=1, pullup=1)) == {"oap": 0, "ols": 0, "pullup": 0}


class TestBaseSets:
    def test_typical_values(self, config, max_reps):
        # min_reps=3, target_mid=22.5 → ceil(22.5/3) = 8
        assert base_sets(max_reps, config) == 8

    def test_uses_most_constraining_exercise(self, config):
        # OLS has fewest reps/set (1), drives base up: ceil(22.5/1) = 23
        mr = MaxReps(oap=6, ols=2, pullup=6)
        assert base_sets(mr, config) == math.ceil(22.5 / 1)

    def test_minimum_one(self, config):
        mr = MaxReps(oap=100, ols=100, pullup=100)
        assert base_sets(mr, config) >= 1


class TestSetsForDay:
    def test_rest_is_zero(self):
        assert sets_for_day(DayType.REST, 8) == 0

    def test_medium_is_base(self):
        assert sets_for_day(DayType.MEDIUM, 8) == 8

    def test_light_is_80_percent(self):
        assert sets_for_day(DayType.LIGHT, 10) == 8

    def test_heavy_is_120_percent(self):
        assert sets_for_day(DayType.HEAVY, 10) == 12

    def test_light_minimum_one(self):
        assert sets_for_day(DayType.LIGHT, 1) == 1


class TestPlanDay:
    def test_rest_day_has_no_sets(self, config, max_reps):
        plan = plan_day(date(2026, 5, 13), DayType.REST, max_reps, config, TZ)
        assert plan.sets == []
        assert plan.day_type == DayType.REST

    def test_medium_set_count(self, config, max_reps):
        plan = plan_day(date(2026, 5, 13), DayType.MEDIUM, max_reps, config, TZ)
        assert len(plan.sets) == sets_for_day(DayType.MEDIUM, base_sets(max_reps, config))

    def test_sets_within_window(self, config, max_reps):
        plan = plan_day(date(2026, 5, 13), DayType.MEDIUM, max_reps, config, TZ)
        window_start = datetime(2026, 5, 13, 8, 0, tzinfo=TZ)
        window_end = datetime(2026, 5, 13, 16, 0, tzinfo=TZ)
        for s in plan.sets:
            assert window_start <= s.scheduled_at <= window_end

    def test_min_gap_respected(self, config, max_reps):
        plan = plan_day(date(2026, 5, 13), DayType.HEAVY, max_reps, config, TZ)
        min_gap = timedelta(minutes=config.min_gap_minutes)
        for a, b in zip(plan.sets, plan.sets[1:], strict=False):
            assert b.scheduled_at - a.scheduled_at >= min_gap - timedelta(microseconds=1)

    def test_set_indices_and_totals(self, config, max_reps):
        plan = plan_day(date(2026, 5, 13), DayType.MEDIUM, max_reps, config, TZ)
        for i, s in enumerate(plan.sets):
            assert s.index == i + 1
            assert s.total == len(plan.sets)

    def test_reps_are_half_max(self, config):
        mr = MaxReps(oap=6, ols=4, pullup=8)
        plan = plan_day(date(2026, 5, 13), DayType.MEDIUM, mr, config, TZ)
        for s in plan.sets:
            assert s.reps == {"oap": 3, "ols": 2, "pullup": 4}

    def test_first_set_at_window_start(self, config, max_reps):
        plan = plan_day(date(2026, 5, 13), DayType.MEDIUM, max_reps, config, TZ)
        assert plan.sets[0].scheduled_at == datetime(2026, 5, 13, 8, 0, tzinfo=TZ)

    def test_last_set_at_window_end(self, config, max_reps):
        plan = plan_day(date(2026, 5, 13), DayType.MEDIUM, max_reps, config, TZ)
        last = plan.sets[-1].scheduled_at
        window_end = datetime(2026, 5, 13, 16, 0, tzinfo=TZ)
        assert abs((last - window_end).total_seconds()) < 1


class TestRescheduleRemaining:
    def _plan(self, config, max_reps, day_type=DayType.MEDIUM):
        return plan_day(date(2026, 5, 13), day_type, max_reps, config, TZ)

    def test_first_rescheduled_set_at_snooze_time(self, config, max_reps):
        plan = self._plan(config, max_reps)
        now = datetime(2026, 5, 13, 8, 0, tzinfo=TZ)
        result = reschedule_remaining(1, 30, plan, config, now)
        assert result.sets[0].scheduled_at == now + timedelta(minutes=30)

    def test_done_sets_times_preserved(self, config, max_reps):
        plan = self._plan(config, max_reps)
        now = datetime(2026, 5, 13, 11, 0, tzinfo=TZ)
        result = reschedule_remaining(4, 15, plan, config, now)
        for i in range(3):
            assert result.sets[i].scheduled_at == plan.sets[i].scheduled_at

    def test_min_gap_respected_after_snooze(self, config, max_reps):
        plan = self._plan(config, max_reps)
        now = datetime(2026, 5, 13, 8, 0, tzinfo=TZ)
        result = reschedule_remaining(1, 15, plan, config, now)
        min_gap = timedelta(minutes=config.min_gap_minutes)
        for a, b in zip(result.sets, result.sets[1:], strict=False):
            assert b.scheduled_at - a.scheduled_at >= min_gap - timedelta(microseconds=1)

    def test_uses_extended_window_when_tight(self, config, max_reps):
        plan = self._plan(config, max_reps)
        # new_start=15:15, 8 sety × 15 min = 17:00 → přesahuje 16:00, vejde se do 18:00
        now = datetime(2026, 5, 13, 15, 0, tzinfo=TZ)
        result = reschedule_remaining(1, 15, plan, config, now)
        extended_end = datetime(2026, 5, 13, 18, 0, tzinfo=TZ)
        for s in result.sets:
            assert s.scheduled_at <= extended_end

    def test_reduces_sets_when_impossible(self, config, max_reps):
        plan = self._plan(config, max_reps)
        # new_start = 18:05, za prodlouženým oknem → sejde se na 1 set
        now = datetime(2026, 5, 13, 17, 50, tzinfo=TZ)
        result = reschedule_remaining(1, 15, plan, config, now)
        assert 1 <= len(result.sets) < len(plan.sets)

    def test_no_remaining_returns_unchanged(self, config, max_reps):
        plan = self._plan(config, max_reps)
        n = len(plan.sets)
        now = datetime(2026, 5, 13, 15, 0, tzinfo=TZ)
        result = reschedule_remaining(n + 1, 15, plan, config, now)
        assert result.sets == plan.sets

    def test_total_updated_in_done_sets(self, config, max_reps):
        plan = self._plan(config, max_reps)
        now = datetime(2026, 5, 13, 15, 0, tzinfo=TZ)
        result = reschedule_remaining(4, 15, plan, config, now)
        # total v done setech musí odpovídat novému celkovému počtu
        assert all(s.total == len(result.sets) for s in result.sets)


TZ_SCHED = ZoneInfo("Europe/Prague")


def _make_plan(times_h: list[int]) -> DayPlan:
    sets = [
        PlannedSet(
            index=i + 1,
            total=len(times_h),
            scheduled_at=datetime(2026, 5, 13, h, 0, tzinfo=TZ_SCHED),
            reps={"oap": 3},
        )
        for i, h in enumerate(times_h)
    ]
    return DayPlan(date="2026-05-13", day_type=DayType.MEDIUM, sets=sets)


class TestNearestPastUncompleted:
    def _now(self, h: int) -> datetime:
        return datetime(2026, 5, 13, h, 0, tzinfo=TZ_SCHED)

    def test_returns_closest_past(self):
        plan = _make_plan([9, 10, 11])
        result = nearest_past_uncompleted(plan, set(), self._now(10))
        assert result is not None
        assert result.index == 2  # 10:00 je nejbližší minulost k 10:00

    def test_latest_done_falls_back_to_previous(self):
        plan = _make_plan([9, 10, 11])
        # set #2 (10:00) splněn → vrátí set #1 (9:00), který je starší a nesplněn
        result = nearest_past_uncompleted(plan, {2}, self._now(10))
        assert result is not None
        assert result.index == 1

    def test_ignores_future_sets(self):
        plan = _make_plan([9, 10, 11])
        result = nearest_past_uncompleted(plan, set(), self._now(9))
        assert result is not None
        assert result.index == 1  # jen set 1 (9:00) je v minulosti

    def test_no_past_sets_returns_none(self):
        plan = _make_plan([10, 11, 12])
        result = nearest_past_uncompleted(plan, set(), self._now(8))
        assert result is None

    def test_all_done_returns_none(self):
        plan = _make_plan([9, 10])
        result = nearest_past_uncompleted(plan, {1, 2}, self._now(11))
        assert result is None
