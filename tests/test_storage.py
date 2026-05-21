import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from gtg.models import (
    AppState,
    CompletedSet,
    CyclePosition,
    DayPlan,
    DayType,
    MaxReps,
    PlannedSet,
)
from gtg.storage import append_history, history_record, load_config, load_state, save_state

TZ = ZoneInfo("Europe/Prague")

RAW_CONFIG = {
    "window": {"start": "08:00", "end": "16:00", "max_extension_hours": 2},
    "scheduling": {"min_gap_minutes": 15, "daily_reps_target": {"min": 15, "max": 30}},
    "cycle": {"work_days": 3, "rest_days": 1, "recalibrate_after_cycles": 2},
    "snooze_options_minutes": [15, 30, 60],
    "ntfy": {"base_url": "https://ntfy.sh", "topic": "test"},
    "exercises": [
        {"id": "oap", "name": "OAP", "unit": "reps"},
        {"id": "ols", "name": "OLS", "unit": "reps"},
        {"id": "pullup", "name": "Shyb", "unit": "reps"},
    ],
    "timezone": "Europe/Prague",
}


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(RAW_CONFIG))
    return p


@pytest.fixture
def sample_state() -> AppState:
    dt = datetime(2026, 5, 13, 8, 0, tzinfo=TZ)
    return AppState(
        max_reps=MaxReps(oap=6, ols=6, pullup=6),
        cycle_position=CyclePosition(cycle_number=1, day_in_cycle=2),
        today_plan=DayPlan(
            date="2026-05-13",
            day_type=DayType.MEDIUM,
            sets=[
                PlannedSet(
                    index=1, total=2, scheduled_at=dt, reps={"oap": 3, "ols": 3, "pullup": 3}
                ),
                PlannedSet(
                    index=2,
                    total=2,
                    scheduled_at=datetime(2026, 5, 13, 12, 0, tzinfo=TZ),
                    reps={"oap": 3, "ols": 3, "pullup": 3},
                ),
            ],
        ),
        completed_sets_today=[
            CompletedSet(
                index=1,
                total=2,
                scheduled_at=dt,
                completed_at=datetime(2026, 5, 13, 8, 5, tzinfo=TZ),
                reps={"oap": 3, "ols": 3, "pullup": 3},
                completed=True,
            )
        ],
        last_calibration_cycle=0,
    )


class TestLoadConfig:
    def test_window(self, config_path):
        config = load_config(config_path)
        assert config.window.start == time(8, 0)
        assert config.window.end == time(16, 0)
        assert config.window.max_extension_hours == 2

    def test_scheduling(self, config_path):
        config = load_config(config_path)
        assert config.min_gap_minutes == 15
        assert config.daily_reps_target_min == 15
        assert config.daily_reps_target_max == 30

    def test_cycle(self, config_path):
        config = load_config(config_path)
        assert config.work_days == 3
        assert config.rest_days == 1
        assert config.recalibrate_after_cycles == 2

    def test_exercises(self, config_path):
        config = load_config(config_path)
        assert len(config.exercises) == 3
        assert config.exercises[0].id == "oap"
        assert config.exercises[2].unit == "reps"

    def test_ntfy_and_timezone(self, config_path):
        config = load_config(config_path)
        assert config.ntfy_topic == "test"
        assert config.timezone == "Europe/Prague"


class TestSaveLoadState:
    def test_missing_file_returns_none(self, tmp_path):
        assert load_state(tmp_path / "state.json", TZ) is None

    def test_round_trip_scalars(self, tmp_path, sample_state):
        path = tmp_path / "state.json"
        save_state(sample_state, path)
        loaded = load_state(path, TZ)
        assert loaded.max_reps == sample_state.max_reps
        assert loaded.cycle_position == sample_state.cycle_position
        assert loaded.last_calibration_cycle == 0

    def test_today_plan_round_trip(self, tmp_path, sample_state):
        path = tmp_path / "state.json"
        save_state(sample_state, path)
        loaded = load_state(path, TZ)
        assert loaded.today_plan.date == "2026-05-13"
        assert loaded.today_plan.day_type == DayType.MEDIUM
        assert len(loaded.today_plan.sets) == 2

    def test_scheduled_at_preserved(self, tmp_path, sample_state):
        path = tmp_path / "state.json"
        save_state(sample_state, path)
        loaded = load_state(path, TZ)
        assert (
            loaded.today_plan.sets[0].scheduled_at == sample_state.today_plan.sets[0].scheduled_at
        )

    def test_completed_sets_round_trip(self, tmp_path, sample_state):
        path = tmp_path / "state.json"
        save_state(sample_state, path)
        loaded = load_state(path, TZ)
        assert len(loaded.completed_sets_today) == 1
        cs = loaded.completed_sets_today[0]
        assert cs.completed is True
        assert cs.reps == {"oap": 3, "ols": 3, "pullup": 3}

    def test_none_today_plan(self, tmp_path):
        state = AppState(
            max_reps=MaxReps(oap=6, ols=6, pullup=6),
            cycle_position=CyclePosition(cycle_number=0, day_in_cycle=0),
            today_plan=None,
        )
        path = tmp_path / "state.json"
        save_state(state, path)
        assert load_state(path, TZ).today_plan is None

    def test_atomic_no_tmp_leftover(self, tmp_path, sample_state):
        path = tmp_path / "state.json"
        save_state(sample_state, path)
        assert not (tmp_path / "state.tmp").exists()

    def test_output_is_valid_json(self, tmp_path, sample_state):
        path = tmp_path / "state.json"
        save_state(sample_state, path)
        data = json.loads(path.read_text())
        assert "max_reps" in data
        assert "cycle_position" in data
        assert "today_plan" in data

    def test_loaded_datetimes_have_tzinfo(self, tmp_path, sample_state):
        path = tmp_path / "state.json"
        save_state(sample_state, path)
        loaded = load_state(path, TZ)
        dt = loaded.today_plan.sets[0].scheduled_at
        assert dt.tzinfo is not None


class TestHistoryRecord:
    def _record(self, completed: bool = True) -> CompletedSet:
        return CompletedSet(
            index=1,
            total=8,
            scheduled_at=datetime(2026, 5, 13, 8, 0, tzinfo=TZ),
            completed_at=datetime(2026, 5, 13, 8, 5, 0, tzinfo=TZ),
            reps={"oap": 3, "ols": 3, "pullup": 3},
            completed=completed,
        )

    def test_all_fields_present(self):
        row = history_record(self._record(), DayType.MEDIUM, "2026-05-13")
        assert row["date"] == "2026-05-13"
        assert row["time"] == "08:05:00"
        assert row["set_index"] == 1
        assert row["set_total"] == 8
        assert row["planned_reps"] == {"oap": 3, "ols": 3, "pullup": 3}
        assert row["completed"] is True
        assert row["day_type"] == "medium"

    def test_skipped_set(self):
        row = history_record(self._record(completed=False), DayType.LIGHT, "2026-05-13")
        assert row["completed"] is False
        assert row["day_type"] == "light"


class TestAppendHistory:
    def _record(self, dt: datetime) -> CompletedSet:
        return CompletedSet(
            index=1,
            total=8,
            scheduled_at=dt,
            completed_at=dt,
            reps={"oap": 3, "ols": 3, "pullup": 3},
            completed=True,
        )

    def test_creates_history_file(self, tmp_path):
        append_history(
            self._record(datetime(2026, 5, 13, 8, 5, tzinfo=TZ)),
            DayType.MEDIUM,
            "2026-05-13",
            tmp_path,
        )
        assert (tmp_path / "history" / "2026-05.jsonl").exists()

    def test_appends_multiple_records(self, tmp_path):
        dt = datetime(2026, 5, 13, 8, 5, tzinfo=TZ)
        for _ in range(3):
            append_history(self._record(dt), DayType.MEDIUM, "2026-05-13", tmp_path)
        lines = (tmp_path / "history" / "2026-05.jsonl").read_text().strip().splitlines()
        assert len(lines) == 3

    def test_separate_files_per_month(self, tmp_path):
        append_history(
            self._record(datetime(2026, 5, 31, 20, 0, tzinfo=TZ)),
            DayType.HEAVY,
            "2026-05-31",
            tmp_path,
        )
        append_history(
            self._record(datetime(2026, 6, 1, 8, 0, tzinfo=TZ)),
            DayType.LIGHT,
            "2026-06-01",
            tmp_path,
        )
        assert (tmp_path / "history" / "2026-05.jsonl").exists()
        assert (tmp_path / "history" / "2026-06.jsonl").exists()

    def test_each_line_is_valid_json(self, tmp_path):
        append_history(
            self._record(datetime(2026, 5, 13, 8, 5, tzinfo=TZ)),
            DayType.MEDIUM,
            "2026-05-13",
            tmp_path,
        )
        lines = (tmp_path / "history" / "2026-05.jsonl").read_text().strip().splitlines()
        for line in lines:
            json.loads(line)
