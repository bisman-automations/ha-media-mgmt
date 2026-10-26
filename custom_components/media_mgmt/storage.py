"""Per-profile persistent state: today's listening, parent controls, timers and schedules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .state import MODE_ENFORCED

STORAGE_VERSION = 1
SAVE_DELAY = 10  # seconds
LOG_SAVE_DELAY = 30  # seconds


def _zero_hours() -> list[int]:
    return [0] * 24


@dataclass
class ProfileState:
    # Controls that survive restarts
    mode: str = MODE_ENFORCED
    music_filter: bool = True
    adult_mode_until: str | None = None  # ISO datetime (UTC)
    force_block: bool = False

    # Sleep timer, and the volume to put back after a fade-out
    sleep_until: str | None = None  # ISO datetime (UTC)
    sleep_fade: int = 0  # minutes
    fade_restore: float | None = None

    # Schedule runs handled: schedule ID -> {"started": day, "faded": day, "stopped": day}
    schedule_runs: dict[str, dict[str, str]] = field(default_factory=dict)

    # Today's counters
    day: str = field(default_factory=lambda: date.today().isoformat())
    used_seconds: int = 0  # counts toward the daily limit
    schedule_seconds: int = 0  # played by a schedule, through the limits
    extension_minutes: int = 0
    blocked_count: int = 0
    last_blocked: str | None = None
    last_blocked_at: str | None = None
    plays: int = 0
    track_seconds: dict[str, int] = field(default_factory=dict)
    artist_seconds: dict[str, int] = field(default_factory=dict)
    album_seconds: dict[str, int] = field(default_factory=dict)
    source_seconds: dict[str, int] = field(default_factory=dict)
    hour_seconds: list[int] = field(default_factory=_zero_hours)

    def __post_init__(self) -> None:
        hours = [int(h or 0) for h in (self.hour_seconds or [])][:24]
        self.hour_seconds = hours + [0] * (24 - len(hours))

    def reset_day(self, day: date) -> None:
        """Start a new day. Extensions and Stop music now don't carry over."""
        self.day = day.isoformat()
        self.used_seconds = 0
        self.schedule_seconds = 0
        self.extension_minutes = 0
        self.blocked_count = 0
        self.force_block = False
        self.plays = 0
        self.track_seconds = {}
        self.artist_seconds = {}
        self.album_seconds = {}
        self.source_seconds = {}
        self.hour_seconds = _zero_hours()

    @property
    def adult_mode_until_dt(self) -> datetime | None:
        return datetime.fromisoformat(self.adult_mode_until) if self.adult_mode_until else None

    @property
    def sleep_until_dt(self) -> datetime | None:
        return datetime.fromisoformat(self.sleep_until) if self.sleep_until else None


class ProfileStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self.state = ProfileState()

    async def async_load(self) -> ProfileState:
        data = await self._store.async_load()
        if data:
            known = ProfileState.__dataclass_fields__
            self.state = ProfileState(**{k: v for k, v in data.items() if k in known})
        return self.state

    def schedule_save(self) -> None:
        self._store.async_delay_save(lambda: asdict(self.state), SAVE_DELAY)

    async def async_save(self) -> None:
        await self._store.async_save(asdict(self.state))

    async def async_remove(self) -> None:
        await self._store.async_remove()


class ActivityStore:
    """A profile's activity log, daily totals and song history."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        from .activity import ActivityLog

        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.activity")
        self.log = ActivityLog()

    async def async_load(self):
        from .activity import ActivityLog

        self.log = ActivityLog(await self._store.async_load())
        return self.log

    def schedule_save(self) -> None:
        self._store.async_delay_save(self.log.as_dict, LOG_SAVE_DELAY)

    async def async_save(self) -> None:
        await self._store.async_save(self.log.as_dict())

    async def async_remove(self) -> None:
        await self._store.async_remove()


class ScheduleStore:
    """A profile's schedules. Kept apart from options so editing them never reloads it."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.schedules")
        self.schedules: list = []

    def _data(self) -> dict[str, Any]:
        return {"schedules": [s.as_dict() for s in self.schedules]}

    async def async_load(self) -> list:
        from .schedules import load_schedules

        data = await self._store.async_load() or {}
        self.schedules = load_schedules(data.get("schedules"))
        return self.schedules

    def schedule_save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    async def async_save(self) -> None:
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        await self._store.async_remove()


class ArtistStore:
    """Saved artists, shared by every speaker in the home."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.artists")
        self.artists: list = []

    def _data(self) -> dict[str, Any]:
        return {"artists": [a.as_dict() for a in self.artists]}

    async def async_load(self) -> list:
        from .artists import load_artists

        data = await self._store.async_load() or {}
        self.artists = load_artists(data.get("artists"))
        return self.artists

    def schedule_save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    async def async_save(self) -> None:
        await self._store.async_save(self._data())
