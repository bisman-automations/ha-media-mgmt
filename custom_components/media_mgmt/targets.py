"""Which speaker to play on: by profile, entity, name, or area.

Shared by the play_artist action, voice and AI assistants, and the
blueprint ("play Brahms on the kids room speaker", or just "play Brahms" to
use the speaker in the same room as the voice assistant).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from .const import DOMAIN
from .media import norm

if TYPE_CHECKING:
    from .manager import MediaManager

# Why no speaker was picked.
NO_SPEAKERS = "no_speakers"
SPEAKER_NOT_FOUND = "speaker_not_found"
SPEAKER_AMBIGUOUS = "speaker_ambiguous"
WHICH_SPEAKER = "which_speaker"


@dataclass
class Target:
    manager: MediaManager | None = None
    error: str | None = None
    detail: str | None = None  # what was asked for


def managers(hass: HomeAssistant) -> list[MediaManager]:
    return [
        e.runtime_data
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]


def entity_area(hass: HomeAssistant, entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    if entry.area_id:
        return entry.area_id
    if entry.device_id and (device := dr.async_get(hass).async_get(entry.device_id)):
        return device.area_id
    return None


def device_area(hass: HomeAssistant, device_id: str | None) -> str | None:
    if device_id and (device := dr.async_get(hass).async_get(device_id)):
        return device.area_id
    return None


def speaker_areas(hass: HomeAssistant, manager: MediaManager) -> set[str]:
    """The speaker's area, and its Music Assistant player's."""
    areas = {
        entity_area(hass, manager.entity_id),
        entity_area(hass, manager.ma_link.entity_id),
    }
    areas.discard(None)
    return areas  # type: ignore[return-value]


def _names(hass: HomeAssistant, manager: MediaManager) -> set[str]:
    names = {
        norm(manager.name),
        norm(manager.player.name),
        norm(manager.entity_id.split(".", 1)[-1].replace("_", " ")),
    }
    if manager.ma_link.entity_id and (
        state := hass.states.get(manager.ma_link.entity_id)
    ):
        names.add(norm(state.name))
    areas = ar.async_get(hass)
    for area_id in speaker_areas(hass, manager):
        if area := areas.async_get_area(area_id):
            names.add(norm(area.name))
            names.update(norm(alias) for alias in area.aliases)
    names.discard("")
    return names


def _by_area(
    hass: HomeAssistant, found: list[MediaManager], area_id: str
) -> list[MediaManager]:
    return [m for m in found if area_id in speaker_areas(hass, m)]


def find_speaker(
    hass: HomeAssistant,
    *,
    profile_id: str | None = None,
    entity_id: str | None = None,
    speaker: str | None = None,
    area_id: str | None = None,
    default_entity: str | None = None,
) -> Target:
    """The speaker to play on.

    Asked for by profile, entity or name: that one, or an error. Otherwise the
    speaker in `area_id` (where the voice assistant is), then `default_entity`
    (a saved artist's default speaker), then the only speaker there is.
    """
    found = managers(hass)
    if not found:
        return Target(error=NO_SPEAKERS)

    if profile_id:
        match = next((m for m in found if m.entry.entry_id == profile_id), None)
        return (
            Target(match)
            if match
            else Target(error=SPEAKER_NOT_FOUND, detail=profile_id)
        )

    if entity_id:
        match = next(
            (m for m in found if entity_id in (m.entity_id, m.ma_link.entity_id)), None
        )
        return (
            Target(match)
            if match
            else Target(error=SPEAKER_NOT_FOUND, detail=entity_id)
        )

    if speaker and speaker.strip():
        wanted = norm(speaker)
        for suffix in (" speaker", " speakers", " homepod", " sonos"):
            if wanted.endswith(suffix) and len(wanted) > len(suffix):
                wanted_short = wanted[: -len(suffix)].strip()
                break
        else:
            wanted_short = wanted
        exact = [m for m in found if {wanted, wanted_short} & _names(hass, m)]
        if len(exact) == 1:
            return Target(exact[0])
        if len(exact) > 1:
            # "the kids room" with two speakers there: prefer the one named exactly.
            named = [m for m in exact if norm(m.name) in (wanted, wanted_short)]
            if len(named) == 1:
                return Target(named[0])
            return Target(error=SPEAKER_AMBIGUOUS, detail=speaker)
        partial = [m for m in found if any(wanted_short in n for n in _names(hass, m))]
        if len(partial) == 1:
            return Target(partial[0])
        return Target(
            error=SPEAKER_AMBIGUOUS if partial else SPEAKER_NOT_FOUND, detail=speaker
        )

    if area_id:
        in_area = _by_area(hass, found, area_id)
        if len(in_area) == 1:
            return Target(in_area[0])
        if len(in_area) > 1:
            area = ar.async_get(hass).async_get_area(area_id)
            return Target(
                error=SPEAKER_AMBIGUOUS, detail=area.name if area else area_id
            )

    if default_entity:
        match = next(
            (m for m in found if default_entity in (m.entity_id, m.ma_link.entity_id)),
            None,
        )
        if match:
            return Target(match)

    if len(found) == 1:
        return Target(found[0])
    return Target(error=WHICH_SPEAKER)


def target_message(target: Target) -> str:
    """Plain words for why no speaker was picked."""
    return {
        NO_SPEAKERS: "No speakers are set up in Media Mgmt",
        SPEAKER_NOT_FOUND: f"Media Mgmt doesn't manage a speaker called {target.detail}",
        SPEAKER_AMBIGUOUS: f"More than one speaker matches {target.detail}; say which one",
        WHICH_SPEAKER: "Which speaker? Say its name or room",
    }.get(target.error or "", "No speaker found")
