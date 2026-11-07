"""Whole-home limits, bedtime fade timing and the Live Activity view (pure modules)."""

from datetime import date, time

from media_mgmt_pure.home import (
    ACTION_NOTIFY,
    ACTION_STOP,
    HomeSettings,
    home_status,
    week_days_before,
    week_start,
)
from media_mgmt_pure.live_view import LiveView, live_view, same_view
from media_mgmt_pure.quiet import parse_windows, seconds_until_quiet
from media_mgmt_pure.state import (
    REASON_BUDGET,
    REASON_HOME_DAILY,
    REASON_HOME_WEEKLY,
    STATE_ENFORCING,
    STATE_OK,
    STATE_WARNING,
    decide,
)
import pytest


def _decide(**over):
    args = {
        "now": time(12, 0),
        "mode": "enforced",
        "adult_mode": False,
        "force_block": False,
        "budget_minutes": 0,
        "extension_minutes": 0,
        "used_seconds": 0,
        "warn_minutes": 5,
        "quiet_windows": [],
    }
    args.update(over)
    return decide(**args)


# ---- decisions with the whole home ----------------------------------------------


def test_home_limit_applies_when_it_has_less_left() -> None:
    d = _decide(
        budget_minutes=60,
        used_seconds=600,
        home_remaining=120,
        home_reason=REASON_HOME_DAILY,
    )
    assert d.state == STATE_WARNING
    assert d.reason == REASON_HOME_DAILY
    assert d.remaining_seconds == 120


def test_speakers_own_limit_wins_when_it_has_less_left() -> None:
    d = _decide(
        budget_minutes=10,
        used_seconds=600,
        home_remaining=3000,
        home_reason=REASON_HOME_DAILY,
    )
    assert (d.state, d.reason) == (STATE_ENFORCING, REASON_BUDGET)


def test_home_limit_without_a_speaker_limit() -> None:
    d = _decide(home_remaining=0, home_reason=REASON_HOME_WEEKLY)
    assert (d.state, d.reason) == (STATE_ENFORCING, REASON_HOME_WEEKLY)
    assert _decide().state == STATE_OK


def test_schedule_still_plays_through_the_home_limit() -> None:
    d = _decide(home_remaining=0, home_reason=REASON_HOME_DAILY, schedule="Bedtime")
    assert d.state == "schedule"


# ---- home settings -------------------------------------------------------------


def test_home_settings_round_trip() -> None:
    settings = HomeSettings.from_dict(
        {
            "daily_minutes": 0,
            "weekly_minutes": 600,
            "notify": ["notify.mobile_app_phone", "notify.mobile_app_phone", " "],
            "summary": ["notify.mobile_app_phone"],
            "excluded": ["abc"],
            "action": ACTION_NOTIFY,
        }
    )
    # 0 is a limit of no time, not "no limit".
    assert settings.daily_minutes == 0 and settings.active
    assert settings.notify == ["notify.mobile_app_phone"]
    assert settings.summary == ["notify.mobile_app_phone"]
    assert not settings.counts("abc") and settings.counts("def")
    assert HomeSettings.from_dict(settings.as_dict()) == settings
    assert HomeSettings().action == ACTION_STOP and not HomeSettings().active


@pytest.mark.parametrize(
    "raw",
    [{"daily_minutes": -1}, {"daily_minutes": "lots"}, {"action": "explode"}],
)
def test_home_settings_refuse_bad_values(raw) -> None:
    with pytest.raises(ValueError):
        HomeSettings.from_dict(raw)


def test_home_status_and_weeks() -> None:
    settings = HomeSettings(daily_minutes=60, weekly_minutes=300)
    status = home_status(
        settings,
        today_seconds=1800,
        week_seconds=17400,
        extension_today=15,
        extension_week=15,
    )
    assert status.daily_remaining == 75 * 60 - 1800
    assert status.weekly_remaining == 315 * 60 - 17400
    assert status.remaining == status.weekly_remaining
    assert status.reason == REASON_HOME_WEEKLY
    wednesday = date(2026, 11, 4)
    assert week_start(wednesday) == date(2026, 11, 2)
    assert week_start(wednesday, "sunday") == date(2026, 11, 1)
    assert week_days_before(wednesday) == ["2026-11-02", "2026-11-03"]


# ---- bedtime fade timing ---------------------------------------------------------


def test_seconds_until_quiet() -> None:
    windows = parse_windows("20:30-07:00 Bedtime, 12:00-13:00")
    assert seconds_until_quiet(windows, time(20, 25)) == 300
    assert seconds_until_quiet(windows, time(11, 59, 30)) == 30
    # Already quiet: stops now.
    assert seconds_until_quiet(windows, time(22, 0)) == 0
    # After midnight, the next start is tomorrow's.
    assert seconds_until_quiet(windows, time(7, 0)) == 5 * 3600
    assert seconds_until_quiet([], time(7, 0)) is None


# ---- Live Activity -------------------------------------------------------------


def test_live_view_counts_down_to_the_end_of_listening_time() -> None:
    view = live_view(
        playing=True,
        state=STATE_OK,
        reason=None,
        remaining_seconds=1800,
        used_seconds=600,
        quiet_window=None,
        schedule=None,
        now=1_000_000,
        clock=lambda epoch: "7:45 PM",
    )
    assert view.headline == "Time left today"
    assert view.message == "Music time ends at 7:45 PM."
    assert view.ends_at == (1_000_000 + 1800) // 60 * 60


def test_live_view_states() -> None:
    def view(**over):
        args = {
            "playing": True,
            "state": STATE_OK,
            "reason": None,
            "remaining_seconds": None,
            "used_seconds": 3720,
            "quiet_window": None,
            "schedule": None,
            "now": 0,
        }
        args.update(over)
        return live_view(**args)

    assert view(playing=False) == LiveView(
        "Music off", "1 h 2 min listened today", "off"
    )
    assert view().headline == "No limit today"
    assert view(
        state=STATE_ENFORCING, reason="quiet_window", quiet_window="Bedtime"
    ).message == ("Bedtime is on. The music is stopping.")
    assert "whole home" in view(state=STATE_ENFORCING, reason=REASON_HOME_DAILY).message
    assert view(state="schedule", schedule="Lullabies").headline == "Lullabies"
    warn = view(state=STATE_WARNING, reason=REASON_HOME_WEEKLY, remaining_seconds=240)
    assert warn.tone == "warn" and warn.message.startswith("The whole home's")


def test_same_view_ignores_small_drift() -> None:
    a = LiveView("Time left today", "x", "ok", 1000)
    assert same_view(a, LiveView("Time left today", "y", "ok", 1060))
    assert not same_view(a, LiveView("Time left today", "x", "ok", 1200))
    assert not same_view(a, LiveView("Time's up", "x", "bad"))
    assert same_view(None, None) and not same_view(a, None)
