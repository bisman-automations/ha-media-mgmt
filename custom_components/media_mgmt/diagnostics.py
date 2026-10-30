"""Diagnostics for Media Mgmt."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import MediaMgmtConfigEntry
from .const import CONF_ANNOUNCE_PLAYERS

# Picture URLs carry an access token that works until Home Assistant restarts,
# and announcement speakers are often named after people.
TO_REDACT = {
    "access_token",
    "token",
    "entity_picture",
    "entity_picture_local",
    "media_image_url",
    "notify",
    CONF_ANNOUNCE_PLAYERS,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MediaMgmtConfigEntry
) -> dict[str, Any]:
    return async_redact_data(_diagnostics(hass, entry), TO_REDACT)


def _diagnostics(hass: HomeAssistant, entry: MediaMgmtConfigEntry) -> dict[str, Any]:
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
            # The Music Assistant player for this speaker and how it was found.
            "music_assistant": {
                **manager.ma_link.as_dict(),
                "playing_through": manager.player.via_twin,
                "target": manager.player.target,
            },
        },
        "quiet_windows": [w.format() for w in manager.quiet_windows],
        "schedules": [s.as_dict() for s in manager.schedules],
        "library_size": len(manager.activity.library),
        "events": len(manager.activity.events),
    }
