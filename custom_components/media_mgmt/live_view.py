"""What a speaker's Live Activity shows. Pure module: no Home Assistant imports.

The Live Activity starts when music starts and shows how much listening time
is left today, counting down on the phone by itself (a chronometer), so it
only needs a push when something visible changes: extra time, a warning, the
time running out, the rules pausing, or the music stopping.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .state import (
    HOME_REASONS,
    REASON_MANUAL,
    REASON_QUIET,
    STATE_ADULT_MODE,
    STATE_ENFORCING,
    STATE_PAUSED,
    STATE_SCHEDULE,
    STATE_WARNING,
)

TONE_OK = "ok"
TONE_WARN = "warn"
TONE_BAD = "bad"
TONE_OFF = "off"


@dataclass(frozen=True)
class LiveView:
    """What the activity shows; compared to decide whether to push."""

    headline: str  # the short status (critical text)
    message: str
    tone: str
    # When the time runs out, epoch seconds rounded to the minute. The phone
    # counts down to it; None when nothing is counting down.
    ends_at: int | None = None


def duration(seconds: float) -> str:
    """'1 h 5 min', '45 min'."""
    total = max(0, round(seconds / 60))
    if total < 60:
        return f"{total} min"
    hours, minutes = divmod(total, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def live_view(
    *,
    playing: bool,
    state: str,
    reason: str | None,
    remaining_seconds: int | None,
    used_seconds: int,
    quiet_window: str | None,
    schedule: str | None,
    now: float,
    clock: Callable[[int], str] | None = None,
) -> LiveView:
    """The activity for this moment.

    ``now`` is epoch seconds; ``clock`` formats an epoch time as the local
    time of day ("7:45 PM") for when the time runs out.
    """
    listened = f"{duration(used_seconds)} listened today"
    if not playing:
        return LiveView("Music off", listened, TONE_OFF)
    if state == STATE_PAUSED:
        return LiveView("Rules paused", "No limits right now.", TONE_OK)
    if state == STATE_ADULT_MODE:
        return LiveView("Adult mode", "Every rule is lifted for now.", TONE_OK)
    if state == STATE_SCHEDULE:
        return LiveView(
            schedule or "Schedule", "Playing through the limits for now.", TONE_OK
        )
    if state == STATE_ENFORCING:
        if reason == REASON_QUIET:
            return LiveView(
                "Quiet time",
                f"{quiet_window or 'A quiet window'} is on. The music is stopping.",
                TONE_BAD,
            )
        if reason == REASON_MANUAL:
            return LiveView("Stopped", "A parent stopped the music for now.", TONE_BAD)
        whose = "the whole home's" if reason in HOME_REASONS else "today's"
        return LiveView("Time's up", f"That's all of {whose} music time.", TONE_BAD)
    if remaining_seconds is None:
        # Time listened isn't shown while playing: it would need a push a minute.
        return LiveView("No limit today", "This speaker has no daily limit.", TONE_OK)
    ends_at = int(now + remaining_seconds) // 60 * 60
    whose = "The whole home's music time" if reason in HOME_REASONS else "Music time"
    message = f"{whose} ends at {clock(ends_at)}." if clock else f"{whose} left today."
    return LiveView(
        "Time left today",
        message,
        TONE_WARN if state == STATE_WARNING else TONE_OK,
        ends_at,
    )


# Between checks the countdown's end can move by a few seconds; that isn't
# worth a push.
ENDS_TOLERANCE = 90


def same_view(a: LiveView | None, b: LiveView | None) -> bool:
    """Whether the phone already shows ``b`` (``a`` is what it shows)."""
    if a is None or b is None:
        return a is b
    if a.headline != b.headline or a.tone != b.tone:
        return False
    if a.ends_at is None or b.ends_at is None:
        return a.ends_at is b.ends_at and a.message == b.message
    return abs(a.ends_at - b.ends_at) <= ENDS_TOLERANCE


def clock_text(hour: int, minute: int) -> str:
    """'7:45 PM'."""
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
