"""Quiet windows: times of day when no music may play.

Pure module (no Home Assistant imports) so it can be unit tested alone.

Format, comma separated:

    HH:MM-HH:MM            e.g. "20:30-07:00"
    HH:MM-HH:MM Label      e.g. "20:30-07:00 Bedtime"

A window whose start is after its end crosses midnight.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class QuietWindow:
    start: time
    end: time
    label: str = ""

    def contains(self, t: time) -> bool:
        if self.start == self.end:
            return False
        if self.start < self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end

    @property
    def name(self) -> str:
        return self.label or f"{self.start:%H:%M}-{self.end:%H:%M}"

    def format(self) -> str:
        text = f"{self.start:%H:%M}-{self.end:%H:%M}"
        return f"{text} {self.label}" if self.label else text


def _parse_time(raw: str) -> time:
    hour, sep, minute = raw.strip().partition(":")
    if not sep or not hour.isdigit() or not minute.isdigit():
        raise ValueError(f"bad time {raw!r}, expected HH:MM")
    h, m = int(hour), int(minute)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"time out of range: {raw!r}")
    return time(h, m)


def parse_window(raw: str) -> QuietWindow:
    text = raw.strip()
    times, _, label = text.partition(" ")
    start_raw, sep, end_raw = times.partition("-")
    if not sep:
        raise ValueError(f"missing '-' in {raw!r}")
    return QuietWindow(_parse_time(start_raw), _parse_time(end_raw), label.strip())


def parse_windows(raw: str | None) -> list[QuietWindow]:
    """Parse a comma-separated list. Raises ValueError on any bad entry."""
    if not raw or not raw.strip():
        return []
    return [parse_window(part) for part in raw.split(",") if part.strip()]


def active_window(windows: list[QuietWindow], t: time) -> QuietWindow | None:
    return next((w for w in windows if w.contains(t)), None)


def seconds_until_quiet(windows: list[QuietWindow], t: time) -> int | None:
    """Seconds from `t` until the next quiet window starts, or None with no windows.

    A window that's already on counts as starting now (0).
    """
    if active_window(windows, t):
        return 0
    now = t.hour * 3600 + t.minute * 60 + t.second
    starts = [
        (w.start.hour * 3600 + w.start.minute * 60 - now) % 86400
        for w in windows
        if w.start != w.end
    ]
    return min(starts) if starts else None
