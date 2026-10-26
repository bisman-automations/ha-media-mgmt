"""Repeating schedules: play music at a set time, fade it out and stop it at another.

Pure module (no Home Assistant imports) so it can be unit tested alone.

A schedule is stored as a dict:

    {
      "id": "a1b2c3d4", "name": "Bedtime music", "enabled": true,
      "days": [0, 1, 2, 3, 6],                 # Monday = 0
      "start": "19:30", "stop": "20:30",       # either may be empty, not both
      "play_kind": "artist", "play_value": "Lullaby Band", "content_type": null,
      "shuffle": true, "repeat": "all",
      "volume": 20,                            # percent, or null to leave it
      "volume_limit": 30,                      # percent: can't go louder while it plays, or null
      "fade_minutes": 10,                      # fade out before the stop time
      "stop_action": "pause",                  # pause / stop / turn_off
      "lift_limits": true,                     # play through limits and quiet windows
    }

With "play_kind": "none" a schedule plays and stops nothing: between its
start and stop times it only limits the volume (an early-morning limit, say).

A run belongs to the day it starts on: with a stop time before the start
time it stops the next morning. With only a stop time a schedule is a
nightly sleep timer: whatever is playing then fades out and stops.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import secrets
from typing import Any

# What a schedule plays
PLAY_ARTIST = "artist"
PLAY_PLAYLIST = "playlist"
PLAY_ALBUM = "album"
PLAY_TRACK = "track"
PLAY_SOURCE = "source"  # a source or favourite on the speaker, e.g. a Sonos favourite
PLAY_CONTENT = "content"  # a media content ID (URI) and type
PLAY_RESUME = "resume"  # press play on whatever played last
PLAY_NONE = (
    "none"  # play nothing: only limit the volume between the start and stop times
)
PLAY_KINDS = [
    PLAY_ARTIST,
    PLAY_PLAYLIST,
    PLAY_ALBUM,
    PLAY_TRACK,
    PLAY_SOURCE,
    PLAY_CONTENT,
    PLAY_RESUME,
    PLAY_NONE,
]

STOP_ACTIONS = ["pause", "stop", "turn_off"]
REPEAT_MODES = ["off", "all", "one"]
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
MAX_FADE = 60  # minutes

# A start or stop missed by up to this long (Home Assistant restarting,
# say) still happens.
GRACE = timedelta(minutes=10)


def new_id() -> str:
    return secrets.token_hex(4)


def parse_hhmm(raw: Any) -> str | None:
    """ "7:45" -> "07:45"; blank -> None. Raises ValueError."""
    if raw is None or str(raw).strip() == "":
        return None
    hour, sep, minute = str(raw).strip()[:5].partition(":")
    if not sep or not hour.isdigit() or not minute.isdigit():
        raise ValueError(f"bad time {raw!r}, expected HH:MM")
    h, m = int(hour), int(minute)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"time out of range: {raw!r}")
    return f"{h:02d}:{m:02d}"


def _time(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class Occurrence:
    """One run of a schedule: the day it belongs to and its times."""

    key: str  # ISO date of the day the run belongs to
    start: datetime | None
    stop: datetime | None
    fade_from: datetime | None

    def contains(self, now: datetime) -> bool:
        """Inside the run's start..stop time (only for schedules with both)."""
        return (
            self.start is not None
            and self.stop is not None
            and self.start <= now < self.stop
        )

    def start_due(self, now: datetime) -> bool:
        if self.start is None or not self.start <= now < self.start + GRACE:
            return False
        return self.stop is None or now < self.stop

    def stop_due(self, now: datetime) -> bool:
        return self.stop is not None and self.stop <= now < self.stop + GRACE

    def fade_due(self, now: datetime) -> bool:
        return (
            self.fade_from is not None
            and self.stop is not None
            and self.fade_from <= now < self.stop
        )


@dataclass
class Schedule:
    id: str
    name: str = "Schedule"
    enabled: bool = True
    days: list[int] = field(default_factory=lambda: list(ALL_DAYS))
    start: str | None = None  # "HH:MM"
    stop: str | None = None
    play_kind: str = PLAY_ARTIST
    play_value: str = ""
    content_type: str | None = None
    shuffle: bool = True
    repeat: str = "all"
    volume: int | None = None
    volume_limit: int | None = None  # can't be turned up past this while it plays
    fade_minutes: int = 0
    stop_action: str = "pause"
    lift_limits: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Schedule:
        """Validate a stored or submitted schedule. Raises ValueError."""
        name = " ".join(str(raw.get("name") or "").split())[:60] or "Schedule"
        try:
            days = sorted(
                {int(d) for d in raw.get("days", ALL_DAYS) if 0 <= int(d) <= 6}
            )
        except (TypeError, ValueError) as err:
            raise ValueError(
                "days must be numbers from 0 (Monday) to 6 (Sunday)"
            ) from err
        if not days:
            raise ValueError("pick at least one day")
        start = parse_hhmm(raw.get("start"))
        stop = parse_hhmm(raw.get("stop"))
        if start is None and stop is None:
            raise ValueError("give a start time, a stop time, or both")
        if start is not None and start == stop:
            raise ValueError("the start and stop times are the same")
        kind = raw.get("play_kind") or PLAY_ARTIST
        if kind not in PLAY_KINDS:
            raise ValueError(f"unknown thing to play {kind!r}")
        value = " ".join(str(raw.get("play_value") or "").split())
        if kind == PLAY_NONE:
            # A volume limit for a stretch of time: it plays and stops nothing.
            if start is None or stop is None:
                raise ValueError("a volume limit needs a start and a stop time")
            if raw.get("volume_limit") in (None, ""):
                raise ValueError("say what to limit the volume to")
        elif start is not None and kind != PLAY_RESUME and not value:
            raise ValueError("say what to play at the start time")
        volume = raw.get("volume")
        volume = None if volume in (None, "") else max(0, min(100, int(volume)))
        limit = raw.get("volume_limit")
        # Only a schedule with a start and a stop time is ever "playing".
        limit = (
            None
            if limit in (None, "") or start is None or stop is None
            else max(5, min(100, int(limit)))
        )
        if limit is not None and volume is not None:
            volume = min(volume, limit)
        fade = max(0, min(MAX_FADE, int(raw.get("fade_minutes") or 0))) if stop else 0
        if kind == PLAY_NONE:
            value, volume, fade = "", None, 0
        repeat = raw.get("repeat") or "all"
        if repeat not in REPEAT_MODES:
            raise ValueError(f"unknown repeat mode {repeat!r}")
        stop_action = raw.get("stop_action") or "pause"
        if stop_action not in STOP_ACTIONS:
            raise ValueError(f"unknown stop action {stop_action!r}")
        return cls(
            id=str(raw.get("id") or new_id()),
            name=name,
            enabled=bool(raw.get("enabled", True)),
            days=days,
            start=start,
            stop=stop,
            play_kind=kind,
            play_value=value,
            content_type=(str(raw.get("content_type") or "").strip() or None),
            shuffle=bool(raw.get("shuffle", True)),
            repeat=repeat,
            volume=volume,
            volume_limit=limit,
            fade_minutes=fade,
            stop_action=stop_action,
            # Only music a schedule plays itself gets through the limits.
            lift_limits=bool(raw.get("lift_limits", True)) and kind != PLAY_NONE,
        )

    @property
    def limit_only(self) -> bool:
        """Plays and stops nothing: only limits the volume during its time."""
        return self.play_kind == PLAY_NONE

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "days": list(self.days),
            "start": self.start,
            "stop": self.stop,
            "play_kind": self.play_kind,
            "play_value": self.play_value,
            "content_type": self.content_type,
            "shuffle": self.shuffle,
            "repeat": self.repeat,
            "volume": self.volume,
            "volume_limit": self.volume_limit,
            "fade_minutes": self.fade_minutes,
            "stop_action": self.stop_action,
            "lift_limits": self.lift_limits,
        }

    # ---- times -----------------------------------------------------------------

    def occurrence(self, day: date, tz) -> Occurrence:
        """The run belonging to `day`."""
        start = (
            datetime.combine(day, _time(self.start), tzinfo=tz) if self.start else None
        )
        stop = None
        fade_from = None
        if self.stop:
            stop = datetime.combine(day, _time(self.stop), tzinfo=tz)
            if start is not None and stop <= start:
                stop += timedelta(days=1)
            if self.fade_minutes:
                fade_from = stop - timedelta(minutes=self.fade_minutes)
                if start is not None:
                    fade_from = max(fade_from, start)
        return Occurrence(day.isoformat(), start, stop, fade_from)

    def occurrences(self, now: datetime) -> list[Occurrence]:
        """Yesterday's and today's runs (yesterday's may stop this morning)."""
        days = (now.date() - timedelta(days=1), now.date())
        return [
            self.occurrence(day, now.tzinfo)
            for day in days
            if day.weekday() in self.days
        ]

    def next_run(self, now: datetime) -> datetime | None:
        """When this schedule next starts (or, with no start, next stops)."""
        for offset in range(0, 9):
            day = now.date() + timedelta(days=offset)
            if day.weekday() not in self.days:
                continue
            occ = self.occurrence(day, now.tzinfo)
            when = occ.start or occ.stop
            if when is not None and when > now:
                return when
        return None


def load_schedules(raw: list[dict[str, Any]] | None) -> list[Schedule]:
    """Stored schedules, skipping any that no longer validate."""
    schedules = []
    for item in raw or []:
        try:
            schedules.append(Schedule.from_dict(item))
        except ValueError, TypeError:
            continue
    return schedules
