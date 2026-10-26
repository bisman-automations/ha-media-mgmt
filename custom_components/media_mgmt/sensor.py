"""Sensors: listening time, enforcement state, now playing, songs, blocks, timers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import MediaMgmtConfigEntry
from .entity import MediaMgmtEntity
from .manager import MediaManager
from .media import describe, track_key
from .state import STATES


@dataclass(frozen=True, kw_only=True)
class MediaMgmtSensorDescription(SensorEntityDescription):
    value_fn: Callable[[MediaManager], Any]
    attrs_fn: Callable[[MediaManager], dict[str, Any]] | None = None


def _minutes(seconds: int | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)


def _ranked(values: dict[str, int], limit: int = 10) -> dict[str, float | None]:
    ranked = sorted(values.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return {k: _minutes(v) for k, v in ranked}


def _now_playing(m: MediaManager) -> str | None:
    p = m.player
    if not p.available:
        return None
    if p.is_on is False:
        return "Off"
    media = p.media
    if media:
        return describe(media)[:255]
    return {"idle": "Idle", "paused": "Paused"}.get(p.state or "", "Nothing playing")


def _now_playing_attrs(m: MediaManager) -> dict[str, Any]:
    media = m.player.media or {}
    rule = m.blocked_rule(media) if media else None
    key = track_key(media)
    return {
        "state": m.player.state,
        "title": media.get("title"),
        "artist": media.get("artist"),
        "album": media.get("album"),
        "source": media.get("source"),
        "allowed": None if not media else rule is None,
        "blocked_by": f"{rule[0]}: {rule[1]}" if rule else None,
        "minutes_today": _minutes(m.state.track_seconds.get(key, 0)) if key else None,
        "volume": round(m.player.volume * 100) if m.player.volume is not None else None,
    }


def _next_schedule(m: MediaManager) -> tuple[datetime | None, str | None]:
    now = dt_util.now()
    upcoming = [(s.next_run(now), s.name) for s in m.schedules if s.enabled]
    upcoming = [u for u in upcoming if u[0]]
    return min(upcoming) if upcoming else (None, None)


SENSORS: tuple[MediaMgmtSensorDescription, ...] = (
    MediaMgmtSensorDescription(
        key="enforcement_state",
        device_class=SensorDeviceClass.ENUM,
        options=STATES,
        value_fn=lambda m: m.decision.state,
        attrs_fn=lambda m: {
            "reason": m.decision.reason,
            "quiet_window": m.decision.quiet_window,
            "schedule": m.decision.schedule,
            "mode": m.state.mode,
            "force_block": m.state.force_block,
        },
    ),
    MediaMgmtSensorDescription(
        key="listening_time_today",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda m: _minutes(m.state.used_seconds),
        attrs_fn=lambda m: {
            "schedule_minutes": _minutes(m.state.schedule_seconds),
            "total_minutes": _minutes(m.state.used_seconds + m.state.schedule_seconds),
        },
    ),
    MediaMgmtSensorDescription(
        key="time_remaining_today",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda m: _minutes(m.decision.remaining_seconds),
        attrs_fn=lambda m: {"daily_limit": m.daily_budget or None},
    ),
    MediaMgmtSensorDescription(
        key="extension_today",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda m: m.state.extension_minutes,
    ),
    MediaMgmtSensorDescription(
        key="now_playing",
        value_fn=_now_playing,
        attrs_fn=_now_playing_attrs,
    ),
    MediaMgmtSensorDescription(
        key="songs_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda m: m.state.plays,
        attrs_fn=lambda m: {
            "top_artists": _ranked(m.state.artist_seconds),
            "top_songs": _ranked(m.state.track_seconds),
            "apps": _ranked(m.state.source_seconds),
        },
    ),
    MediaMgmtSensorDescription(
        key="blocked_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda m: m.state.blocked_count,
        attrs_fn=lambda m: {
            "last_blocked": m.state.last_blocked,
            "last_blocked_at": m.state.last_blocked_at,
        },
    ),
    MediaMgmtSensorDescription(
        key="sleep_timer",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda m: m.state.sleep_until_dt,
        attrs_fn=lambda m: {
            "fade_minutes": m.state.sleep_fade if m.state.sleep_until else None
        },
    ),
    MediaMgmtSensorDescription(
        key="next_schedule",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda m: _next_schedule(m)[0],
        attrs_fn=lambda m: {
            "schedule": _next_schedule(m)[1],
            "schedules": [
                {
                    "name": s.name,
                    "enabled": s.enabled,
                    "start": s.start,
                    "stop": s.stop,
                    "days": s.days,
                }
                for s in m.schedules
            ],
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MediaMgmtConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    async_add_entities(MediaMgmtSensor(manager, d) for d in SENSORS)


class MediaMgmtSensor(MediaMgmtEntity, SensorEntity):
    entity_description: MediaMgmtSensorDescription

    def __init__(
        self, manager: MediaManager, description: MediaMgmtSensorDescription
    ) -> None:
        super().__init__(manager, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.manager)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.manager)
