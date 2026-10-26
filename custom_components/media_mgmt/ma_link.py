"""Find a speaker's Music Assistant player.

Sonos, HomePod (Apple TV integration) and other speakers can't search a
streaming service for an artist themselves. Music Assistant can, and when it
also runs the same speaker, Media Mgmt plays through it. This finds that
Music Assistant player, tried in this order:

1. The speaker is a Music Assistant player itself.
2. The one picked by hand in the speaker's settings.
3. Music Assistant's Home Assistant players provider: the player ID is the
   speaker's entity ID.
4. Sonos: the player ID is the Sonos ID (RINCON_...) Home Assistant's Sonos
   integration uses too.
5. AirPlay (HomePod, Apple TV, AirPlay speakers): the player ID is "ap" and
   the speaker's MAC address, which Home Assistant's device lists.
6. The same name, or the only Music Assistant player in the speaker's area.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import MUSIC_ASSISTANT_DOMAIN
from .media import norm

MP_DOMAIN = "media_player"

# How the Music Assistant player was found.
LINK_SELF = "self"
LINK_MANUAL = "manual"
LINK_ENTITY_ID = "entity_id"
LINK_SONOS = "sonos"
LINK_AIRPLAY = "airplay"
LINK_MAC = "mac"
LINK_NAME = "name"
LINK_AREA = "area"

_HEX = re.compile(r"[^0-9a-f]")


@dataclass
class MALink:
    """The Music Assistant player for a speaker, and how it was found."""

    entity_id: str | None = None
    method: str | None = None
    config_entry_id: str | None = None
    player_id: str | None = None  # Music Assistant's own ID for the player
    detail: str | None = None  # why there's no link, or a problem with the one picked

    @property
    def linked(self) -> bool:
        return self.entity_id is not None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mac(value: str | None) -> str:
    """A MAC address as 12 lowercase hex digits, or "" if it isn't one."""
    digits = _HEX.sub("", (value or "").lower())
    return digits if len(digits) == 12 else ""


def ma_entities(hass: HomeAssistant) -> list[er.RegistryEntry]:
    """Music Assistant's media players that are turned on in Home Assistant."""
    return [
        e
        for e in er.async_get(hass).entities.values()
        if e.platform == MUSIC_ASSISTANT_DOMAIN
        and e.domain == MP_DOMAIN
        and not e.disabled
    ]


def _found(entry: er.RegistryEntry, method: str, detail: str | None = None) -> MALink:
    return MALink(
        entity_id=entry.entity_id,
        method=method,
        config_entry_id=entry.config_entry_id,
        player_id=entry.unique_id,
        detail=detail,
    )


def _area(hass: HomeAssistant, entry: er.RegistryEntry | None) -> str | None:
    if entry is None:
        return None
    if entry.area_id:
        return entry.area_id
    if entry.device_id and (device := dr.async_get(hass).async_get(entry.device_id)):
        return device.area_id
    return None


def _names(
    hass: HomeAssistant, entity_id: str, entry: er.RegistryEntry | None
) -> set[str]:
    names = set()
    if state := hass.states.get(entity_id):
        names.add(norm(state.name))
    if entry is not None:
        for name in (entry.name, entry.original_name):
            if name:
                names.add(norm(name))
        if entry.device_id and (
            device := dr.async_get(hass).async_get(entry.device_id)
        ):
            for name in (device.name_by_user, device.name):
                if name:
                    names.add(norm(name))
    names.discard("")
    return names


def resolve(hass: HomeAssistant, entity_id: str, override: str | None = None) -> MALink:
    """The Music Assistant player that runs this speaker, if there is one."""
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is not None and entry.platform == MUSIC_ASSISTANT_DOMAIN:
        return _found(entry, LINK_SELF)

    problem: str | None = None
    if override:
        picked = registry.async_get(override)
        if (
            picked is not None
            and picked.platform == MUSIC_ASSISTANT_DOMAIN
            and not picked.disabled
        ):
            return _found(picked, LINK_MANUAL)
        problem = f"The Music Assistant player picked in the settings, {override}, isn't there any more"

    players = ma_entities(hass)
    if not players:
        return MALink(
            detail=problem or "Music Assistant isn't set up, or has no players"
        )

    def done(found: er.RegistryEntry, method: str) -> MALink:
        return _found(found, method, problem)

    # Music Assistant's Home Assistant players provider uses the entity ID.
    for player in players:
        if player.unique_id == entity_id:
            return done(player, LINK_ENTITY_ID)

    if entry is not None:
        # Sonos: Music Assistant and Home Assistant both use the RINCON ID.
        if entry.platform == "sonos" and entry.unique_id:
            wanted = entry.unique_id.casefold()
            for player in players:
                if player.unique_id.casefold() == wanted:
                    return done(player, LINK_SONOS)

        # AirPlay and others named after the MAC address.
        device = (
            dr.async_get(hass).async_get(entry.device_id) if entry.device_id else None
        )
        macs = {
            mac
            for kind, value in (device.connections if device else set())
            if kind == dr.CONNECTION_NETWORK_MAC and (mac := _mac(value))
        }
        if macs:
            for player in players:
                pid = player.unique_id.lower()
                if pid.startswith("ap") and _mac(pid[2:]) in macs:
                    return done(player, LINK_AIRPLAY)
            for player in players:
                if (
                    _mac(player.unique_id[-17:]) in macs
                    or _mac(player.unique_id[-12:]) in macs
                ):
                    return done(player, LINK_MAC)

    # Same name, as long as only one Music Assistant player has it.
    names = _names(hass, entity_id, entry)
    by_name = [p for p in players if names & _names(hass, p.entity_id, p)]
    if len(by_name) == 1:
        return done(by_name[0], LINK_NAME)

    # The only Music Assistant player in the speaker's area.
    if (area := _area(hass, entry)) is not None:
        in_area = [p for p in players if _area(hass, p) == area]
        if len(in_area) == 1:
            return done(in_area[0], LINK_AREA)

    detail = problem or (
        "More than one Music Assistant player has this speaker's name; pick one in the speaker's settings"
        if len(by_name) > 1
        else "No Music Assistant player matches this speaker; pick one in the speaker's settings"
    )
    return MALink(detail=detail)


def ma_config_entry(hass: HomeAssistant, link: MALink | None = None) -> str | None:
    """The Music Assistant config entry to search with."""
    if link is not None and link.config_entry_id:
        return link.config_entry_id
    loaded = [
        e.entry_id
        for e in hass.config_entries.async_entries(MUSIC_ASSISTANT_DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]
    return loaded[0] if len(loaded) == 1 else None


def is_available(hass: HomeAssistant, entity_id: str | None) -> bool:
    state = hass.states.get(entity_id) if entity_id else None
    return state is not None and state.state != STATE_UNAVAILABLE
