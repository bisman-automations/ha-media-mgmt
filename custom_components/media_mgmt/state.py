"""Enforcement decisions.

Pure module (no Home Assistant imports) so it can be unit tested alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from .quiet import QuietWindow, active_window

# Modes (select entity)
MODE_ENFORCED = "enforced"
MODE_MONITOR_ONLY = "monitor_only"
MODE_PAUSED = "paused"
MODES = [MODE_ENFORCED, MODE_MONITOR_ONLY, MODE_PAUSED]

# Enforcement states (sensor)
STATE_OK = "ok"
STATE_WARNING = "warning"
STATE_ENFORCING = "enforcing"
STATE_SCHEDULE = "schedule"  # a schedule's music is playing through the limits
STATE_PAUSED = "paused"
STATE_ADULT_MODE = "adult_mode"
STATES = [
    STATE_OK,
    STATE_WARNING,
    STATE_ENFORCING,
    STATE_SCHEDULE,
    STATE_PAUSED,
    STATE_ADULT_MODE,
]

# Why music isn't allowed
REASON_MANUAL = "manual"
REASON_QUIET = "quiet_window"
REASON_BUDGET = "budget"
# The whole home's listening time (home.py) ran out
REASON_HOME_DAILY = "home_daily"
REASON_HOME_WEEKLY = "home_weekly"
HOME_REASONS = (REASON_HOME_DAILY, REASON_HOME_WEEKLY)


@dataclass(frozen=True)
class Decision:
    state: str
    reason: str | None = None
    quiet_window: str | None = None
    remaining_seconds: int | None = None  # None = unlimited
    schedule: str | None = None  # the schedule playing through the limits

    @property
    def blocked(self) -> bool:
        return self.state == STATE_ENFORCING

    @property
    def filter_active(self) -> bool:
        """Blocked songs and artists are skipped (music that may play at all)."""
        return self.state in (STATE_OK, STATE_WARNING, STATE_SCHEDULE)


def decide(
    *,
    now: time,
    mode: str,
    adult_mode: bool,
    force_block: bool,
    budget_minutes: int,
    extension_minutes: int,
    used_seconds: int,
    warn_minutes: int,
    quiet_windows: list[QuietWindow],
    schedule: str | None = None,
    home_remaining: int | None = None,
    home_reason: str | None = None,
) -> Decision:
    """What should be true about the speaker right now.

    budget_minutes == 0 means no daily limit. A schedule playing (bedtime
    music, say) lifts the daily limit and quiet windows while it runs, but
    not a parent's Stop music now. The decision is the same in monitor-only
    mode; the caller just doesn't act on it.

    ``home_remaining`` is the whole home's time left when the home's limit
    stops speakers (``home_reason`` says which limit); whichever of the
    speaker's and the home's time has less left applies.
    """
    remaining: int | None = None
    limit_reason = REASON_BUDGET
    if budget_minutes > 0:
        remaining = (budget_minutes + extension_minutes) * 60 - used_seconds
    if home_remaining is not None and (remaining is None or home_remaining < remaining):
        remaining = home_remaining
        limit_reason = home_reason or REASON_HOME_DAILY

    if mode == MODE_PAUSED:
        return Decision(STATE_PAUSED, remaining_seconds=remaining)
    if adult_mode:
        return Decision(STATE_ADULT_MODE, remaining_seconds=remaining)
    if force_block:
        return Decision(STATE_ENFORCING, REASON_MANUAL, remaining_seconds=remaining)
    if schedule:
        return Decision(STATE_SCHEDULE, remaining_seconds=remaining, schedule=schedule)
    if window := active_window(quiet_windows, now):
        return Decision(STATE_ENFORCING, REASON_QUIET, window.name, remaining)
    if remaining is not None:
        if remaining <= 0:
            return Decision(STATE_ENFORCING, limit_reason, remaining_seconds=0)
        if remaining <= warn_minutes * 60:
            return Decision(STATE_WARNING, limit_reason, remaining_seconds=remaining)
    return Decision(STATE_OK, remaining_seconds=remaining)
