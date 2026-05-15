from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from gtg.models import Config, Exercise, PlannedSet, WindowConfig
from gtg.notifier import Notifier


def make_config() -> Config:
    return Config(
        window=WindowConfig(start=None, end=None, max_extension_hours=2),
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


def make_planned_set() -> PlannedSet:
    return PlannedSet(
        index=2,
        total=5,
        scheduled_at=datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc),
        reps={"oap": 3, "ols": 2, "pullup": 1},
    )


@pytest.fixture
def notifier() -> Notifier:
    return Notifier(config=make_config(), callback_base_url="https://tunnel.example.com")


def test_topic_url(notifier: Notifier) -> None:
    assert notifier._topic_url() == "https://ntfy.sh/gtg-test"


def test_reps_label(notifier: Notifier) -> None:
    label = notifier._reps_label(make_planned_set())
    assert label == "OAP: 3× / OLS: 2× / Shyb: 1×"


def test_actions_header_contains_done(notifier: Notifier) -> None:
    actions = notifier._actions_header(make_planned_set())
    assert "Hotovo" in actions
    assert "/callback/done" in actions


def test_actions_header_contains_first_snooze_option(notifier: Notifier) -> None:
    # ntfy limit: max 3 actions — only first snooze option is included
    actions = notifier._actions_header(make_planned_set())
    assert "minutes=15" in actions
    assert "minutes=30" not in actions
    assert "minutes=60" not in actions


def test_actions_header_contains_skip(notifier: Notifier) -> None:
    actions = notifier._actions_header(make_planned_set())
    assert "/callback/skip" in actions


def test_actions_header_uses_callback_base_url(notifier: Notifier) -> None:
    actions = notifier._actions_header(make_planned_set())
    assert "https://tunnel.example.com" in actions


@patch("gtg.notifier.httpx.Client")
def test_send_set_notification_posts_to_topic(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client

    notifier = Notifier(config=make_config(), callback_base_url="https://tunnel.example.com")
    notifier.send_set_notification(make_planned_set())

    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://ntfy.sh/gtg-test"
    body = kwargs["content"].decode()
    assert "set #2 z 5" in body
    assert "OAP: 3×" in body
    assert "Actions" in kwargs["headers"]


@patch("gtg.notifier.httpx.Client")
def test_send_calibration_reminder_high_priority(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client

    notifier = Notifier(config=make_config(), callback_base_url="https://tunnel.example.com")
    notifier.send_calibration_reminder()

    _, kwargs = mock_client.post.call_args
    assert kwargs["headers"]["Priority"] == b"high"


@patch("gtg.notifier.httpx.Client")
def test_send_skip_confirmation(mock_client_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client

    notifier = Notifier(config=make_config(), callback_base_url="https://tunnel.example.com")
    notifier.send_skip_confirmation()

    mock_client.post.assert_called_once()
