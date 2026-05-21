from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from gtg.models import (
    AppState,
    Config,
    CyclePosition,
    DayPlan,
    DayType,
    MaxReps,
    PlannedSet,
)

# Pořadí typů dnů v rámci jednoho cyklu (spec 2.4: light → heavy → medium)
_WORK_DAY_TYPES = [DayType.LIGHT, DayType.HEAVY, DayType.MEDIUM]


def day_type_for_position(position: CyclePosition, config: Config) -> DayType:
    cycle_length = config.work_days + config.rest_days
    pos = position.day_in_cycle % cycle_length
    if pos < config.work_days:
        return _WORK_DAY_TYPES[pos % len(_WORK_DAY_TYPES)]
    return DayType.REST


def advance_cycle(position: CyclePosition, config: Config) -> CyclePosition:
    cycle_length = config.work_days + config.rest_days
    new_day = position.day_in_cycle + 1
    if new_day >= cycle_length:
        return CyclePosition(cycle_number=position.cycle_number + 1, day_in_cycle=0)
    return CyclePosition(cycle_number=position.cycle_number, day_in_cycle=new_day)


def needs_recalibration(state: AppState, config: Config) -> bool:
    cycles_since = state.cycle_position.cycle_number - state.last_calibration_cycle
    return cycles_since >= config.recalibrate_after_cycles


def set_reps(max_reps: MaxReps) -> dict[str, int]:
    """Vrátí počet opakování na set: ⌊½ × max_reps⌋ pro každý cvik."""
    return {
        "oap": math.floor(max_reps.oap / 2),
        "ols": math.floor(max_reps.ols / 2),
        "pullup": math.floor(max_reps.pullup / 2),
    }


def base_sets(max_reps: MaxReps, config: Config) -> int:
    """Vypočítá základní počet setů tak, aby denní objem per cvik byl v cílovém rozsahu."""
    reps = set_reps(max_reps)
    min_reps = min(reps.values())
    if min_reps == 0:
        return 1
    target = (config.daily_reps_target_min + config.daily_reps_target_max) / 2
    return max(1, math.ceil(target / min_reps))


def sets_for_day(day_type: DayType, base: int) -> int:
    match day_type:
        case DayType.REST:
            return 0
        case DayType.LIGHT:
            return max(1, round(base * 0.8))
        case DayType.HEAVY:
            return round(base * 1.2)
        case _:  # MEDIUM
            return base


def _distribute_times(
    start: datetime,
    end: datetime,
    n: int,
    min_gap: timedelta,
) -> list[datetime]:
    if n <= 0:
        return []
    if n == 1:
        return [start]
    step = max((end - start) / (n - 1), min_gap)
    return [start + step * i for i in range(n)]


def plan_day(
    for_date: date,
    day_type: DayType,
    max_reps: MaxReps,
    config: Config,
    tz: ZoneInfo,
) -> DayPlan:
    base = base_sets(max_reps, config)
    n = sets_for_day(day_type, base)
    reps = set_reps(max_reps)

    window_start = datetime.combine(for_date, config.window.start, tzinfo=tz)
    window_end = datetime.combine(for_date, config.window.end, tzinfo=tz)
    min_gap = timedelta(minutes=config.min_gap_minutes)

    times = _distribute_times(window_start, window_end, n, min_gap)
    sets = [
        PlannedSet(index=i + 1, total=n, scheduled_at=t, reps=reps) for i, t in enumerate(times)
    ]
    return DayPlan(date=for_date.isoformat(), day_type=day_type, sets=sets)


def reschedule_remaining(
    from_set_index: int,
    snooze_minutes: int,
    current_plan: DayPlan,
    config: Config,
    now: datetime,
) -> DayPlan:
    """Přeplánuje set from_set_index a všechny následující po snoozu."""
    done_sets = [s for s in current_plan.sets if s.index < from_set_index]
    n = len([s for s in current_plan.sets if s.index >= from_set_index])

    if n == 0:
        return current_plan

    new_start = now + timedelta(minutes=snooze_minutes)
    tz = new_start.tzinfo
    plan_date = new_start.date()
    min_gap = timedelta(minutes=config.min_gap_minutes)

    window_end = datetime.combine(plan_date, config.window.end, tzinfo=tz)
    extended_end = window_end + timedelta(hours=config.window.max_extension_hours)

    def fits(end: datetime) -> bool:
        return n == 1 or new_start + min_gap * (n - 1) <= end

    if fits(window_end):
        times = _distribute_times(new_start, window_end, n, min_gap)
    elif fits(extended_end):
        times = _distribute_times(new_start, extended_end, n, min_gap)
    else:
        # Sníž počet setů na maximum, které se vejde do prodlouženého okna
        n = max(1, int((extended_end - new_start) / min_gap) + 1)
        times = _distribute_times(new_start, extended_end, n, min_gap)

    total = len(done_sets) + len(times)
    reps = current_plan.sets[0].reps

    updated_done = [
        PlannedSet(index=s.index, total=total, scheduled_at=s.scheduled_at, reps=s.reps)
        for s in done_sets
    ]
    new_sets = [
        PlannedSet(
            index=len(done_sets) + i + 1,
            total=total,
            scheduled_at=t,
            reps=reps,
            snoozed=True,
        )
        for i, t in enumerate(times)
    ]

    return DayPlan(
        date=current_plan.date,
        day_type=current_plan.day_type,
        sets=updated_done + new_sets,
        skipped=current_plan.skipped,
    )


def nearest_past_uncompleted(
    plan: DayPlan,
    done_indices: set[int],
    now: datetime,
) -> PlannedSet | None:
    """Vrátí nejpozdější nehotový set v minulosti. Jinak None."""
    candidates = [s for s in plan.sets if s.scheduled_at <= now and s.index not in done_indices]
    return max(candidates, key=lambda s: s.scheduled_at) if candidates else None
