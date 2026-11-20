"""Diagnostics for Media Mgmt.

Everything personal is redacted before it is shown or downloaded:

- picture links (``entity_picture``, ``media_image_url``), which carry an
  access token that works until Home Assistant restarts;
- tokens and API keys anywhere;
- who did something: the user ID in the speaker state's context;
- phones (the notify services for the Live Activity and the weekly summary)
  and announcement speakers, which are often named after people;
- the query string of any web address, such as a stream or a picture from a
  music service (``...?token=...``, ``X-Plex-Token``, ``authSig``), at any
  depth, so a token in a link isn't missed because its key isn't listed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
import re
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant

from . import MediaMgmtConfigEntry
from .const import CONF_ANNOUNCE_PLAYERS, CONF_LIVE_ACTIVITY

TO_REDACT = {
    "access_token",
    "token",
    "api_key",
    "password",
    "Authorization",
    "entity_picture",
    "entity_picture_local",
    "media_image_url",
    "notify",
    # The state's context: who changed the speaker.
    "user_id",
    "parent_id",
    CONF_ANNOUNCE_PLAYERS,
    CONF_LIVE_ACTIVITY,
}

# A web address with a query string; the part after "?" is replaced.
_URL_QUERY = re.compile(
    r"(?P<base>\b[a-z][a-z0-9+.-]*://[^\s?#\"']+)\?[^\s#\"']*", re.I
)


def scrub_urls(value: Any) -> Any:
    """Replace the query string of every web address in ``value``, at any depth."""
    if isinstance(value, str):
        return _URL_QUERY.sub(lambda m: f"{m['base']}?{REDACTED}", value)
    if isinstance(value, Mapping):
        return {key: scrub_urls(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [scrub_urls(item) for item in value]
    return value


def redact(data: Mapping[str, Any]) -> dict[str, Any]:
    """The diagnostics with every personal value replaced."""
    return scrub_urls(async_redact_data(data, TO_REDACT))


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MediaMgmtConfigEntry
) -> dict[str, Any]:
    return redact(_diagnostics(hass, entry))


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
        # Open repair issues for this profile (a deleted speaker, say).
        "issues": _issues(hass, entry),
    }


def _issues(hass: HomeAssistant, entry: MediaMgmtConfigEntry) -> list[str]:
    from homeassistant.helpers import issue_registry as ir

    from .const import DOMAIN
    from .references import ISSUE_KINDS, issue_id

    registry = ir.async_get(hass)
    return [
        kind
        for kind in ISSUE_KINDS
        if registry.async_get_issue(DOMAIN, issue_id(kind, entry.entry_id))
    ]
