from datetime import datetime, time
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

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
from gtg.server import AppContext, create_app

TZ = ZoneInfo("Europe/Prague")
NOW = datetime(2026, 5, 13, 10, 0, tzinfo=TZ)


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


def make_plan(n: int = 3) -> DayPlan:
    sets = [
        PlannedSet(
            index=i + 1,
            total=n,
            scheduled_at=datetime(2026, 5, 13, 9 + i, 0, tzinfo=TZ),
            reps={"oap": 3, "ols": 2, "pullup": 1},
        )
        for i in range(n)
    ]
    return DayPlan(date="2026-05-13", day_type=DayType.MEDIUM, sets=sets)


def make_state(plan: DayPlan | None = None) -> AppState:
    return AppState(
        max_reps=MaxReps(oap=6, ols=4, pullup=2),
        cycle_position=CyclePosition(cycle_number=1, day_in_cycle=2),
        today_plan=plan or make_plan(),
    )


@pytest.fixture
def ctx(tmp_path: Path) -> AppContext:
    notifier = MagicMock(spec=Notifier)
    return AppContext(
        config=make_config(),
        config_path=tmp_path / "config.yaml",
        state_path=tmp_path / "state.json",
        data_dir=tmp_path,
        tz=TZ,
        notifier=notifier,
        reschedule_fn=MagicMock(),
        cancel_today_fn=MagicMock(),
        cancel_set_fn=MagicMock(),
        apply_config_fn=MagicMock(),
    )


@pytest.fixture
def client(ctx: AppContext, tmp_path: Path) -> TestClient:
    from gtg.storage import save_state

    save_state(make_state(), ctx.state_path)
    return TestClient(create_app(ctx))


# ── /callback/done ─────────────────────────────────────────────────────────────


@patch("gtg.server.datetime")
def test_done_records_nearest_past_set(
    mock_dt: MagicMock, client: TestClient, ctx: AppContext
) -> None:
    # NOW=10:00; sets at 9:00 (idx 1), 10:00 (idx 2), 11:00 (idx 3)
    # nearest past uncompleted = set 2 (scheduled_at=10:00, closest to now)
    mock_dt.now.return_value = NOW

    resp = client.post("/callback/done")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "set": 2}

    from gtg.storage import load_state

    state = load_state(ctx.state_path, TZ)
    assert len(state.completed_sets_today) == 1
    assert state.completed_sets_today[0].index == 2
    assert state.completed_sets_today[0].completed is True


@patch("gtg.server.datetime")
def test_done_appends_history(mock_dt: MagicMock, client: TestClient, ctx: AppContext) -> None:
    mock_dt.now.return_value = NOW
    client.post("/callback/done")
    history_file = ctx.data_dir / "history" / "2026-05.jsonl"
    assert history_file.exists()
    lines = history_file.read_text().strip().splitlines()
    assert len(lines) == 1


@patch("gtg.server.datetime")
def test_done_no_past_sets_returns_404(mock_dt: MagicMock, client: TestClient) -> None:
    # before first set (8:00), no past uncompleted set exists
    mock_dt.now.return_value = datetime(2026, 5, 13, 7, 0, tzinfo=TZ)
    resp = client.post("/callback/done")
    assert resp.status_code == 404


@patch("gtg.server.datetime")
def test_done_with_set_index_completes_future_set(
    mock_dt: MagicMock, client: TestClient, ctx: AppContext
) -> None:
    # set 3 is at 11:00, NOW=10:00 — future, but explicit index allows completing it
    mock_dt.now.return_value = NOW
    resp = client.post("/callback/done?set=3")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "set": 3}
    ctx.cancel_set_fn.assert_called_once_with("2026-05-13", 3)


@patch("gtg.server.datetime")
def test_done_with_set_index_already_done_returns_404(
    mock_dt: MagicMock, client: TestClient, ctx: AppContext
) -> None:
    mock_dt.now.return_value = NOW
    client.post("/callback/done?set=1")
    resp = client.post("/callback/done?set=1")
    assert resp.status_code == 404


def test_done_no_plan_returns_404(ctx: AppContext, tmp_path: Path) -> None:
    from gtg.storage import save_state

    state = make_state()
    state.today_plan = None
    save_state(state, ctx.state_path)
    c = TestClient(create_app(ctx))
    assert c.post("/callback/done").status_code == 404


# ── /callback/snooze ───────────────────────────────────────────────────────────


@patch("gtg.server.datetime")
def test_snooze_calls_reschedule_fn(
    mock_dt: MagicMock, client: TestClient, ctx: AppContext
) -> None:
    mock_dt.now.return_value = NOW
    resp = client.post("/callback/snooze?set=2&minutes=15")
    assert resp.status_code == 200
    ctx.reschedule_fn.assert_called_once()
    new_plan: DayPlan = ctx.reschedule_fn.call_args[0][0]
    assert isinstance(new_plan, DayPlan)


@patch("gtg.server.datetime")
def test_snooze_saves_updated_plan(mock_dt: MagicMock, client: TestClient, ctx: AppContext) -> None:
    mock_dt.now.return_value = NOW
    client.post("/callback/snooze?set=2&minutes=30")

    from gtg.storage import load_state

    state = load_state(ctx.state_path, TZ)
    remaining = [s for s in state.today_plan.sets if s.index >= 2]
    first_remaining_time = remaining[0].scheduled_at
    assert first_remaining_time >= NOW


def test_snooze_invalid_duration_returns_400(client: TestClient) -> None:
    resp = client.post("/callback/snooze?set=1&minutes=999")
    assert resp.status_code == 400


# ── /callback/skip ─────────────────────────────────────────────────────────────


def test_skip_marks_plan_skipped(client: TestClient, ctx: AppContext) -> None:
    resp = client.post("/callback/skip")
    assert resp.status_code == 200

    from gtg.storage import load_state

    state = load_state(ctx.state_path, TZ)
    assert state.today_plan.skipped is True


def test_skip_calls_cancel_and_notifier(client: TestClient, ctx: AppContext) -> None:
    client.post("/callback/skip")
    ctx.cancel_today_fn.assert_called_once()
    ctx.notifier.send_skip_confirmation.assert_called_once()


def test_skip_no_plan_returns_404(ctx: AppContext, tmp_path: Path) -> None:
    from gtg.storage import save_state

    state = make_state()
    state.today_plan = None
    save_state(state, ctx.state_path)
    c = TestClient(create_app(ctx))
    assert c.post("/callback/skip").status_code == 404
