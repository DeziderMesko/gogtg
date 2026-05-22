import json
import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import jsonlines
import yaml

from gtg.models import (
    AppState,
    CompletedSet,
    Config,
    CyclePosition,
    DayPlan,
    DayType,
    Exercise,
    MaxReps,
    PlannedSet,
    WindowConfig,
)


def load_config(path: Path) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)

    w = raw["window"]
    start_h, start_m = map(int, w["start"].split(":"))
    end_h, end_m = map(int, w["end"].split(":"))

    return Config(
        window=WindowConfig(
            start=time(start_h, start_m),
            end=time(end_h, end_m),
            max_extension_hours=int(w["max_extension_hours"]),
        ),
        min_gap_minutes=int(raw["scheduling"]["min_gap_minutes"]),
        daily_reps_target_min=int(raw["scheduling"]["daily_reps_target"]["min"]),
        daily_reps_target_max=int(raw["scheduling"]["daily_reps_target"]["max"]),
        work_days=int(raw["cycle"]["work_days"]),
        rest_days=int(raw["cycle"]["rest_days"]),
        recalibrate_after_cycles=int(raw["cycle"]["recalibrate_after_cycles"]),
        snooze_options_minutes=list(raw["snooze_options_minutes"]),
        ntfy_base_url=raw["ntfy"]["base_url"],
        ntfy_topic=raw["ntfy"]["topic"],
        exercises=[Exercise(id=e["id"], name=e["name"], unit=e["unit"]) for e in raw["exercises"]],
        timezone=raw["timezone"],
    )


def save_config(path: Path, config: Config) -> None:
    raw = {
        "window": {
            "start": config.window.start.strftime("%H:%M"),
            "end": config.window.end.strftime("%H:%M"),
            "max_extension_hours": config.window.max_extension_hours,
        },
        "scheduling": {
            "min_gap_minutes": config.min_gap_minutes,
            "daily_reps_target": {
                "min": config.daily_reps_target_min,
                "max": config.daily_reps_target_max,
            },
        },
        "cycle": {
            "work_days": config.work_days,
            "rest_days": config.rest_days,
            "recalibrate_after_cycles": config.recalibrate_after_cycles,
        },
        "snooze_options_minutes": config.snooze_options_minutes,
        "ntfy": {
            "base_url": config.ntfy_base_url,
            "topic": config.ntfy_topic,
        },
        "exercises": [{"id": e.id, "name": e.name, "unit": e.unit} for e in config.exercises],
        "timezone": config.timezone,
    }
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    tmp.replace(path)


# ── Serializace / deserializace ────────────────────────────────────────────────


def _parse_dt(s: str, tz: ZoneInfo) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt.astimezone(tz) if dt.tzinfo is not None else dt.replace(tzinfo=tz)


def _ser_planned_set(s: PlannedSet) -> dict:
    d: dict = {
        "index": s.index,
        "total": s.total,
        "scheduled_at": s.scheduled_at.isoformat(),
        "reps": s.reps,
    }
    if s.original_scheduled_at is not None:
        d["original_scheduled_at"] = s.original_scheduled_at.isoformat()
    return d


def _deser_planned_set(d: dict, tz: ZoneInfo) -> PlannedSet:
    orig = d.get("original_scheduled_at")
    return PlannedSet(
        index=d["index"],
        total=d["total"],
        scheduled_at=_parse_dt(d["scheduled_at"], tz),
        reps=d["reps"],
        original_scheduled_at=_parse_dt(orig, tz) if orig else None,
    )


def _ser_completed_set(s: CompletedSet) -> dict:
    return {
        "index": s.index,
        "total": s.total,
        "scheduled_at": s.scheduled_at.isoformat(),
        "completed_at": s.completed_at.isoformat(),
        "reps": s.reps,
        "completed": s.completed,
    }


def _deser_completed_set(d: dict, tz: ZoneInfo) -> CompletedSet:
    return CompletedSet(
        index=d["index"],
        total=d["total"],
        scheduled_at=_parse_dt(d["scheduled_at"], tz),
        completed_at=_parse_dt(d["completed_at"], tz),
        reps=d["reps"],
        completed=d["completed"],
    )


def _ser_day_plan(plan: DayPlan) -> dict:
    return {
        "date": plan.date,
        "day_type": plan.day_type.value,
        "sets": [_ser_planned_set(s) for s in plan.sets],
        "skipped": plan.skipped,
    }


def _deser_day_plan(d: dict, tz: ZoneInfo) -> DayPlan:
    return DayPlan(
        date=d["date"],
        day_type=DayType(d["day_type"]),
        sets=[_deser_planned_set(s, tz) for s in d["sets"]],
        skipped=d.get("skipped", False),
    )


def _ser_state(state: AppState) -> dict:
    return {
        "max_reps": {
            "oap": state.max_reps.oap,
            "ols": state.max_reps.ols,
            "pullup": state.max_reps.pullup,
        },
        "cycle_position": {
            "cycle_number": state.cycle_position.cycle_number,
            "day_in_cycle": state.cycle_position.day_in_cycle,
        },
        "today_plan": _ser_day_plan(state.today_plan) if state.today_plan else None,
        "completed_sets_today": [_ser_completed_set(s) for s in state.completed_sets_today],
        "last_calibration_cycle": state.last_calibration_cycle,
        "plan_date": state.plan_date,
    }


def _deser_state(d: dict, tz: ZoneInfo) -> AppState:
    return AppState(
        max_reps=MaxReps(**d["max_reps"]),
        cycle_position=CyclePosition(**d["cycle_position"]),
        today_plan=_deser_day_plan(d["today_plan"], tz) if d.get("today_plan") else None,
        completed_sets_today=[
            _deser_completed_set(s, tz) for s in d.get("completed_sets_today", [])
        ],
        last_calibration_cycle=d.get("last_calibration_cycle", 0),
        plan_date=d.get("plan_date"),
    )


# ── Veřejné IO funkce ──────────────────────────────────────────────────────────


def load_state(path: Path, tz: ZoneInfo) -> AppState | None:
    if not path.exists():
        return None
    with open(path) as f:
        return _deser_state(json.load(f), tz)


def save_state(state: AppState, path: Path) -> None:
    """Atomický zápis přes tmp soubor + rename (bezpečné i na Windows)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_ser_state(state), ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def history_record(record: CompletedSet, day_type: DayType, plan_date: str) -> dict:
    """Sestaví řádek pro JSONL historii (pole dle spec 2.9)."""
    return {
        "date": plan_date,
        "time": record.completed_at.time().isoformat(),
        "set_index": record.index,
        "set_total": record.total,
        "planned_reps": record.reps,
        "completed": record.completed,
        "day_type": day_type.value,
    }


def append_history(record: CompletedSet, day_type: DayType, plan_date: str, data_dir: Path) -> None:
    month = plan_date[:7]
    history_dir = data_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    with jsonlines.open(history_dir / f"{month}.jsonl", mode="a") as writer:
        writer.write(history_record(record, day_type, plan_date))
