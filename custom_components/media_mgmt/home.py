"""Whole-home limits: listening time added up across every speaker in the home.

Pure module (no Home Assistant imports) so it can be unit tested alone.

Each speaker's listening time counts, so two speakers playing for an hour is
two hours of the home's time. A limit can be daily, weekly, or both; the one
with less time left is the one that applies. Time a schedule plays (bedtime
music) doesn't count, as with each speaker's own limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

# Why a speaker is stopped by the home (Decision.reason)
REASON_HOME_DAILY = "home_daily"
REASON_HOME_WEEKLY = "home_weekly"
HOME_REASONS = (REASON_HOME_DAILY, REASON_HOME_WEEKLY)

# What happens when the home's time runs out
ACTION_STOP = "stop"  # the speakers stop, like their own limits
ACTION_NOTIFY = "notify"  # only the people picked are told
ACTIONS = [ACTION_STOP, ACTION_NOTIFY]

WEEK_STARTS = {"monday": 0, "sunday": 6}  # date.weekday() of the first day

DEFAULT_WARN_MINUTES = 10
MAX_MINUTES_DAY = 1440
MAX_MINUTES_WEEK = 7 * 1440
# Kept with the settings so a later change to what a number means can tell
# old settings apart (as TV Mgmt's 1.20.0 did).
LIMITS_VERSION = 1


@dataclass
class HomeSettings:
    # None: no limit. 0 is a limit of no time at all, so only extra time
    # given (earned) lets music play.
    daily_minutes: int | None = None
    weekly_minutes: int | None = None
    week_start: str = "monday"
    warn_minutes: int = DEFAULT_WARN_MINUTES
    action: str = ACTION_STOP
    notify: list[str] = field(default_factory=list)  # notify services or entities
    excluded: list[str] = field(
        default_factory=list
    )  # speaker profiles (entry IDs) that don't count
    summary: list[str] = field(
        default_factory=list
    )  # notify services or entities for the weekly summary

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> HomeSettings:
        """Validate stored or submitted settings. Raises ValueError."""
        raw = raw or {}

        def limit(key: str, top: int) -> int | None:
            value = raw.get(key)
            if value is None or value == "":
                return None
            return minutes(key, top)

        def minutes(key: str, top: int) -> int:
            value = raw.get(key) or 0
            try:
                value = int(value)
            except (TypeError, ValueError) as err:
                raise ValueError(f"{key} must be a whole number of minutes") from err
            if not 0 <= value <= top:
                raise ValueError(f"{key} must be from 0 to {top} minutes")
            return value

        week_start = raw.get("week_start") or "monday"
        if week_start not in WEEK_STARTS:
            raise ValueError(f"unknown first day of the week {week_start!r}")
        action = raw.get("action") or ACTION_STOP
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        return cls(
            daily_minutes=limit("daily_minutes", MAX_MINUTES_DAY),
            weekly_minutes=limit("weekly_minutes", MAX_MINUTES_WEEK),
            week_start=week_start,
            warn_minutes=minutes("warn_minutes", 120)
            if raw.get("warn_minutes") is not None
            else DEFAULT_WARN_MINUTES,
            action=action,
            notify=_targets(raw.get("notify")),
            excluded=list(
                dict.fromkeys(str(e) for e in raw.get("excluded") or [] if e)
            ),
            summary=_targets(raw.get("summary")),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "limits": LIMITS_VERSION,
            "daily_minutes": self.daily_minutes,
            "weekly_minutes": self.weekly_minutes,
            "week_start": self.week_start,
            "warn_minutes": self.warn_minutes,
            "action": self.action,
            "notify": list(self.notify),
            "excluded": list(self.excluded),
            "summary": list(self.summary),
        }

    @property
    def active(self) -> bool:
        """Is there any home limit at all?"""
        return self.daily_minutes is not None or self.weekly_minutes is not None

    def counts(self, entry_id: str) -> bool:
        return entry_id not in self.excluded


def _targets(raw: Any) -> list[str]:
    return list(dict.fromkeys(str(t).strip() for t in raw or [] if str(t).strip()))


def week_start(day: date, first_day: str = "monday") -> date:
    """The first day of the week `day` is in."""
    return day - timedelta(days=(day.weekday() - WEEK_STARTS[first_day]) % 7)


def week_days_before(day: date, first_day: str = "monday") -> list[str]:
    """ISO dates of this week's days before `day`, oldest first."""
    start = week_start(day, first_day)
    return [(start + timedelta(days=i)).isoformat() for i in range((day - start).days)]


@dataclass(frozen=True)
class HomeStatus:
    today_seconds: int
    week_seconds: int
    daily_remaining: int | None  # None = no daily limit
    weekly_remaining: int | None  # None = no weekly limit
    extension_minutes: int = 0  # extra time today

    @property
    def remaining(self) -> int | None:
        """Seconds left under whichever limit has less left."""
        left = [
            r for r in (self.daily_remaining, self.weekly_remaining) if r is not None
        ]
        return min(left) if left else None

    @property
    def reason(self) -> str | None:
        """Which limit `remaining` comes from. On a tie, the weekly one (it lasts longer)."""
        if self.weekly_remaining is not None and (
            self.daily_remaining is None
            or self.weekly_remaining <= self.daily_remaining
        ):
            return REASON_HOME_WEEKLY
        if self.daily_remaining is not None:
            return REASON_HOME_DAILY
        return None


def home_status(
    settings: HomeSettings,
    *,
    today_seconds: int,
    week_seconds: int,
    extension_today: int = 0,
    extension_week: int = 0,
) -> HomeStatus:
    """Time used and left.

    Extra time given today adds to today's limit; extra time given on any day
    this week (today included) adds to the weekly limit, so it isn't taken back
    the next day.
    """
    daily = weekly = None
    if settings.daily_minutes is not None:
        daily = (settings.daily_minutes + extension_today) * 60 - today_seconds
    if settings.weekly_minutes is not None:
        weekly = (settings.weekly_minutes + extension_week) * 60 - week_seconds
    return HomeStatus(
        int(today_seconds), int(week_seconds), daily, weekly, extension_today
    )
