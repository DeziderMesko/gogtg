from dataclasses import dataclass, field
from datetime import datetime, time
from enum import StrEnum
from typing import Literal


@dataclass
class WindowConfig:
    start: time
    end: time
    max_extension_hours: int


@dataclass
class Exercise:
    id: str
    name: str
    unit: Literal["reps", "seconds"]


@dataclass
class Config:
    window: WindowConfig
    min_gap_minutes: int
    daily_reps_target_min: int
    daily_reps_target_max: int
    work_days: int
    rest_days: int
    recalibrate_after_cycles: int
    snooze_options_minutes: list[int]
    ntfy_base_url: str
    ntfy_topic: str
    exercises: list[Exercise]
    timezone: str


class DayType(StrEnum):
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"
    REST = "rest"


@dataclass
class PlannedSet:
    index: int
    total: int
    scheduled_at: datetime
    reps: dict[str, int]
    snoozed: bool = False
    original_scheduled_at: datetime | None = None


@dataclass
class CompletedSet:
    index: int
    total: int
    scheduled_at: datetime
    completed_at: datetime
    reps: dict[str, int]
    completed: bool


@dataclass
class DayPlan:
    date: str
    day_type: DayType
    sets: list[PlannedSet]
    skipped: bool = False


@dataclass
class MaxReps:
    oap: int
    ols: int
    pullup: int


@dataclass
class CyclePosition:
    cycle_number: int
    day_in_cycle: int


@dataclass
class AppState:
    max_reps: MaxReps
    cycle_position: CyclePosition
    today_plan: DayPlan | None
    completed_sets_today: list[CompletedSet] = field(default_factory=list)
    last_calibration_cycle: int = 0
    plan_date: str | None = None  # datum posledního rolloveru, i pro REST dny
