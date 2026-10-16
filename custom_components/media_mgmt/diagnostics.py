"""Diagnostics for Media Mgmt."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import MediaMgmtConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: MediaMgmtConfigEntry) -> dict[str, Any]:
    manager = entry.runtime_data
    player_state = hass.states.get(manager.entity_id)
    return {
        "data": dict(entry.data),
        "options": dict(entry.options),
        "profile_state": asdict(manager.state),
        "decision": asdict(manager.decision),
        "player": {
            "platform": manager.player.platform,
            "capabilities": manager.player.capabilities(),
            "media": manager.player.media,
            "state": player_state.as_dict() if player_state else None,
        },
        "quiet_windows": [w.format() for w in manager.quiet_windows],
        "schedules": [s.as_dict() for s in manager.schedules],
        "library_size": len(manager.activity.library),
        "events": len(manager.activity.events),
    }
