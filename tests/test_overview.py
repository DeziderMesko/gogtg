import json
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

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
from gtg.overview import (
    DayRow,
    _day_from_history,
    _day_future,
    _day_today,
    _read_history,
    build_month_rows,
    render_html,
)

TZ = ZoneInfo("Europe/Prague")
TODAY = date.today()


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
        exercises=[
            Exercise(id="oap", name="OAP", unit="reps"),
            Exercise(id="ols", name="OLS", unit="reps"),
            Exercise(id="pullup", name="Shyb", unit="reps"),
        ],
        timezone="Europe/Prague",
    )


def make_state(plan: DayPlan | None = None) -> AppState:
    return AppState(
        max_reps=MaxReps(oap=6, ols=4, pullup=2),
        cycle_position=CyclePosition(cycle_number=1, day_in_cycle=2),
        today_plan=plan,
    )


# ── _read_history ──────────────────────────────────────────────────────────────


def test_read_history_missing_file(tmp_path: Path) -> None:
    result = _read_history(tmp_path, 2026, 5)
    assert result == {}


def test_read_history_groups_by_date(tmp_path: Path) -> None:
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    lines = [
        json.dumps({"date": "2026-05-10", "time": "09:00:00", "set_index": 1, "set_total": 3,
                    "planned_reps": {"oap": 3, "ols": 2, "pullup": 1}, "completed": True, "day_type": "medium"}),
        json.dumps({"date": "2026-05-10", "time": "10:00:00", "set_index": 2, "set_total": 3,
                    "planned_reps": {"oap": 3, "ols": 2, "pullup": 1}, "completed": True, "day_type": "medium"}),
        json.dumps({"date": "2026-05-11", "time": "09:00:00", "set_index": 1, "set_total": 2,
                    "planned_reps": {"oap": 3, "ols": 2, "pullup": 1}, "completed": False, "day_type": "light"}),
    ]
    (history_dir / "2026-05.jsonl").write_text("\n".join(lines))
    result = _read_history(tmp_path, 2026, 5)
    assert len(result["2026-05-10"]) == 2
    assert len(result["2026-05-11"]) == 1


# ── _day_from_history ──────────────────────────────────────────────────────────


def test_day_from_history_no_records() -> None:
    row = _day_from_history(date(2026, 5, 10), [], make_config())
    assert row.day_type is None
    assert row.sets == []


def test_day_from_history_all_done() -> None:
    records = [
        {"date": "2026-05-10", "time": "09:05:00", "set_index": 1, "set_total": 2,
         "planned_reps": {"oap": 3, "ols": 2, "pullup": 1}, "completed": True, "day_type": "medium"},
        {"date": "2026-05-10", "time": "10:05:00", "set_index": 2, "set_total": 2,
         "planned_reps": {"oap": 3, "ols": 2, "pullup": 1}, "completed": True, "day_type": "medium"},
    ]
    row = _day_from_history(date(2026, 5, 10), records, make_config())
    assert row.day_type == DayType.MEDIUM
    assert len(row.sets) == 2
    assert all(s.done for s in row.sets)
    assert "09:05" in row.sets[0].tooltip


def test_day_from_history_partial() -> None:
    records = [
        {"date": "2026-05-10", "time": "09:00:00", "set_index": 1, "set_total": 3,
         "planned_reps": {"oap": 3, "ols": 2, "pullup": 1}, "completed": True, "day_type": "heavy"},
    ]
    row = _day_from_history(date(2026, 5, 10), records, make_config())
    assert len(row.sets) == 3
    assert row.sets[0].done is True
    assert row.sets[1].done is False
    assert row.sets[2].done is False


def test_day_from_history_reps_label() -> None:
    records = [
        {"date": "2026-05-10", "time": "09:00:00", "set_index": 1, "set_total": 1,
         "planned_reps": {"oap": 3, "ols": 2, "pullup": 1}, "completed": True, "day_type": "light"},
    ]
    row = _day_from_history(date(2026, 5, 10), records, make_config())
    assert row.reps_label == "3/2/1"
    assert "OAP" in row.reps_tooltip


# ── _day_today ─────────────────────────────────────────────────────────────────


def test_day_today_rest_when_no_plan() -> None:
    state = make_state(plan=None)
    row = _day_today(TODAY, state, make_config(), TZ, [])
    assert row.day_type == DayType.REST
    assert row.sets == []


def test_day_today_shows_planned_sets() -> None:
    plan = DayPlan(
        date="2026-05-13",
        day_type=DayType.MEDIUM,
        sets=[
            PlannedSet(index=1, total=2, scheduled_at=datetime(2026, 5, 13, 9, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
            PlannedSet(index=2, total=2, scheduled_at=datetime(2026, 5, 13, 11, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
        ],
    )
    state = make_state(plan=plan)
    row = _day_today(TODAY, state, make_config(), TZ, [])
    assert len(row.sets) == 2
    assert not row.sets[0].done
    assert "09:00" in row.sets[0].tooltip


def test_day_today_marks_completed() -> None:
    plan = DayPlan(
        date="2026-05-13",
        day_type=DayType.MEDIUM,
        sets=[
            PlannedSet(index=1, total=2, scheduled_at=datetime(2026, 5, 13, 9, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
            PlannedSet(index=2, total=2, scheduled_at=datetime(2026, 5, 13, 11, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
        ],
    )
    state = make_state(plan=plan)
    state.completed_sets_today = [
        CompletedSet(
            index=1, total=2,
            scheduled_at=datetime(2026, 5, 13, 9, 0, tzinfo=TZ),
            completed_at=datetime(2026, 5, 13, 9, 5, tzinfo=TZ),
            reps={"oap": 3, "ols": 2, "pullup": 1},
            completed=True,
        )
    ]
    row = _day_today(TODAY, state, make_config(), TZ, [])
    assert row.sets[0].done is True
    assert row.sets[1].done is False


def test_day_today_marks_completed_from_history() -> None:
    plan = DayPlan(
        date="2026-05-13",
        day_type=DayType.MEDIUM,
        sets=[
            PlannedSet(index=1, total=2, scheduled_at=datetime(2026, 5, 13, 9, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
            PlannedSet(index=2, total=2, scheduled_at=datetime(2026, 5, 13, 11, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
        ],
    )
    state = make_state(plan=plan)
    hist = [{"set_index": 1, "completed": True}]
    row = _day_today(TODAY, state, make_config(), TZ, hist)
    assert row.sets[0].done is True
    assert row.sets[1].done is False


def test_day_today_next_notify_highlights_nearest_future_set() -> None:
    # Sety daleko v budoucnosti — next_notify musí označit první nesplněný
    plan = DayPlan(
        date="2099-06-01",
        day_type=DayType.MEDIUM,
        sets=[
            PlannedSet(index=1, total=3, scheduled_at=datetime(2099, 6, 1, 9, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
            PlannedSet(index=2, total=3, scheduled_at=datetime(2099, 6, 1, 11, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
            PlannedSet(index=3, total=3, scheduled_at=datetime(2099, 6, 1, 13, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
        ],
    )
    state = make_state(plan=plan)
    row = _day_today(date(2099, 6, 1), state, make_config(), TZ, [])
    assert row.sets[0].next_notify is True
    assert row.sets[1].next_notify is False
    assert row.sets[2].next_notify is False


def test_day_today_next_notify_skips_done_sets() -> None:
    plan = DayPlan(
        date="2099-06-01",
        day_type=DayType.MEDIUM,
        sets=[
            PlannedSet(index=1, total=2, scheduled_at=datetime(2099, 6, 1, 9, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
            PlannedSet(index=2, total=2, scheduled_at=datetime(2099, 6, 1, 11, 0, tzinfo=TZ), reps={"oap": 3, "ols": 2, "pullup": 1}),
        ],
    )
    state = make_state(plan=plan)
    hist = [{"set_index": 1, "completed": True}]
    row = _day_today(date(2099, 6, 1), state, make_config(), TZ, hist)
    assert row.sets[0].next_notify is False  # hotovo
    assert row.sets[1].next_notify is True   # první nesplněný budoucí


# ── _day_future ────────────────────────────────────────────────────────────────


def test_day_future_rest() -> None:
    state = make_state()
    row = _day_future(date(2026, 5, 20), DayType.REST, state, make_config())
    assert row.day_type == DayType.REST
    assert row.sets == []


def test_day_future_work_day_has_squares() -> None:
    state = make_state()
    row = _day_future(date(2026, 5, 20), DayType.MEDIUM, state, make_config())
    assert len(row.sets) > 0
    assert all(not s.done for s in row.sets)
    assert all(s.tooltip == "naplánováno" for s in row.sets)


# ── build_month_rows ───────────────────────────────────────────────────────────


def test_build_month_rows_length(tmp_path: Path) -> None:
    import calendar

    state = make_state()
    config = make_config()
    rows = build_month_rows(state, config, TZ, tmp_path)
    assert len(rows) == calendar.monthrange(TODAY.year, TODAY.month)[1]


def test_build_month_rows_today_is_medium(tmp_path: Path) -> None:
    t = datetime.combine(TODAY, time(10, 0), tzinfo=TZ)
    plan = DayPlan(
        date=TODAY.isoformat(),
        day_type=DayType.MEDIUM,
        sets=[PlannedSet(index=1, total=1, scheduled_at=t, reps={"oap": 3, "ols": 2, "pullup": 1})],
    )
    state = make_state(plan=plan)
    rows = build_month_rows(state, make_config(), TZ, tmp_path)
    today_row = next(r for r in rows if r.date == TODAY)
    assert today_row.day_type == DayType.MEDIUM


# ── render_html ────────────────────────────────────────────────────────────────


def test_render_html_contains_month_title() -> None:
    rows: list[DayRow] = []
    html = render_html(rows, 2026, 5, [15, 30, 60])
    assert "Květen 2026" in html


def test_render_html_contains_legend() -> None:
    html = render_html([], 2026, 5, [15, 30, 60])
    assert "Splněno" in html
    assert "□" in html
    assert "■" in html


def test_render_html_today_row_is_bold(tmp_path: Path) -> None:
    t = datetime.combine(TODAY, time(9, 0), tzinfo=TZ)
    plan = DayPlan(
        date=TODAY.isoformat(),
        day_type=DayType.MEDIUM,
        sets=[PlannedSet(index=1, total=1, scheduled_at=t, reps={"oap": 3, "ols": 2, "pullup": 1})],
    )
    state = make_state(plan=plan)
    rows = build_month_rows(state, make_config(), TZ, tmp_path)
    html = render_html(rows, TODAY.year, TODAY.month, [15, 30, 60])
    assert 'class="today"' in html or '<tr class="today"' in html


def test_render_html_rest_day_shows_dash(tmp_path: Path) -> None:
    state = make_state(plan=None)
    rows = build_month_rows(state, make_config(), TZ, tmp_path)
    html = render_html(rows, TODAY.year, TODAY.month, [15, 30, 60])
    assert "Rest" in html
    assert "—" in html


def test_render_html_reps_label_in_output(tmp_path: Path) -> None:
    t = datetime.combine(TODAY, time(9, 0), tzinfo=TZ)
    plan = DayPlan(
        date=TODAY.isoformat(),
        day_type=DayType.MEDIUM,
        sets=[PlannedSet(index=1, total=1, scheduled_at=t, reps={"oap": 3, "ols": 2, "pullup": 1})],
    )
    state = make_state(plan=plan)
    rows = build_month_rows(state, make_config(), TZ, tmp_path)
    html = render_html(rows, TODAY.year, TODAY.month, [15, 30, 60])
    assert "3/2/1" in html
    assert 'class="reps"' in html
