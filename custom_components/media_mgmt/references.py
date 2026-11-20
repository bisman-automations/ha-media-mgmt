"""Entities a speaker profile points at: following renames, and repairs.

A profile is set up for one speaker (``media_player`` in the entry's data) and
its settings may name a Music Assistant player picked by hand (Playback), a
voice for warnings and speakers to say them on (Warnings). They are stored by
entity ID, so two things can go wrong:

- **The entity ID is changed** (Settings → Entities → the speaker → Entity ID).
  Before 1.7.0 the profile kept watching the old ID, which no longer has a
  state, so it saw a speaker that never plays: listening time stopped
  counting and limits, quiet times and blocked music stopped working, with
  nothing to say so. Now the profile follows the rename: the entry's data,
  unique ID and settings move to the new ID, and the update listener reloads
  the profile with it.
- **The entity is deleted** (the speaker or the Music Assistant player was
  removed from Home Assistant). Then a repair issue says so under Settings →
  Repairs, and its Fix button lets you pick another speaker (or another Music
  Assistant player, or let Media Mgmt find it again). The issue goes away by
  itself when the entity comes back. Reconfigure on the integration's entry
  does the same for the speaker at any time.

"Missing" means neither the entity registry nor the state machine knows the
entity. An unavailable speaker (switched off, its integration not loaded yet)
is still registered, so it is not reported. Checks wait until Home Assistant
has started, so entities from integrations that load later aren't reported
while Home Assistant starts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_STATE_CHANGED
from homeassistant.core import (
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .const import (
    CONF_ANNOUNCE_PLAYERS,
    CONF_ANNOUNCE_TTS,
    CONF_MA_PLAYER,
    CONF_MEDIA_PLAYER,
    DOMAIN,
    SECTION_ANNOUNCE,
    SECTION_PLAYBACK,
)

_LOGGER = logging.getLogger(__name__)

# Repair issue kinds (translation keys under "issues" in strings.json). The
# issue ID is "<kind>_<entry_id>", so each profile has its own.
ISSUE_SPEAKER_MISSING = "speaker_missing"
ISSUE_MA_PLAYER_MISSING = "music_assistant_player_missing"
ISSUE_KINDS = (ISSUE_SPEAKER_MISSING, ISSUE_MA_PLAYER_MISSING)

# Settings that hold one entity ID: (section, key).
_SINGLE_OPTIONS = (
    (SECTION_PLAYBACK, CONF_MA_PLAYER),
    (SECTION_ANNOUNCE, CONF_ANNOUNCE_TTS),
)
# Settings that hold a list of entity IDs: (section, key).
_LIST_OPTIONS = ((SECTION_ANNOUNCE, CONF_ANNOUNCE_PLAYERS),)


def issue_id(kind: str, entry_id: str) -> str:
    """The repair issue ID for one profile."""
    return f"{kind}_{entry_id}"


@callback
def entity_missing(hass: HomeAssistant, entity_id: str | None) -> bool:
    """Neither the entity registry nor the state machine knows the entity."""
    if not entity_id:
        return False
    return (
        er.async_get(hass).async_get(entity_id) is None
        and hass.states.get(entity_id) is None
    )


# ---- renames -------------------------------------------------------------------------


def renamed_options(
    options: Mapping[str, Any], old_id: str, new_id: str
) -> dict[str, Any] | None:
    """The settings with ``old_id`` replaced by ``new_id``, or None if unchanged.

    Options are grouped into the form's sections (see config_flow); only the
    settings that hold entity IDs are looked at.
    """
    changed = False
    new: dict[str, Any] = {
        key: dict(value) if isinstance(value, Mapping) else value
        for key, value in options.items()
    }
    for section, key in _SINGLE_OPTIONS:
        group = new.get(section)
        if isinstance(group, dict) and group.get(key) == old_id:
            group[key] = new_id
            changed = True
    for section, key in _LIST_OPTIONS:
        group = new.get(section)
        if isinstance(group, dict) and old_id in (group.get(key) or []):
            group[key] = [new_id if e == old_id else e for e in group[key]]
            changed = True
    return new if changed else None


@callback
def async_follow_rename(
    hass: HomeAssistant, entry: ConfigEntry, old_id: str, new_id: str
) -> bool:
    """Point the profile at an entity's new ID. True when anything changed.

    A new speaker ID also becomes the entry's unique ID (which keeps the same
    speaker from being added twice), unless another profile already has it.
    The update listener (``_async_update_listener`` in __init__.py) then
    reloads the profile for a new speaker, since the speaker's state is
    watched by its ID, and applies settings (the Music Assistant player, the
    warning voice and speakers) live.
    """
    changes: dict[str, Any] = {}
    if entry.data.get(CONF_MEDIA_PLAYER) == old_id:
        changes["data"] = {**entry.data, CONF_MEDIA_PLAYER: new_id}
        if entry.unique_id == old_id and not _unique_id_taken(hass, entry, new_id):
            changes["unique_id"] = new_id
    if (options := renamed_options(entry.options, old_id, new_id)) is not None:
        changes["options"] = options
    if not changes:
        return False
    _LOGGER.info(
        "Media Mgmt %s: %s was renamed to %s; following it", entry.title, old_id, new_id
    )
    hass.config_entries.async_update_entry(entry, **changes)
    return True


def _unique_id_taken(hass: HomeAssistant, entry: ConfigEntry, unique_id: str) -> bool:
    return any(
        other.unique_id == unique_id and other.entry_id != entry.entry_id
        for other in hass.config_entries.async_entries(DOMAIN)
    )


def speaker_taken(
    hass: HomeAssistant, entry: ConfigEntry | None, entity_id: str
) -> bool:
    """Another profile already manages this speaker."""
    return any(
        (other.unique_id == entity_id or other.data.get(CONF_MEDIA_PLAYER) == entity_id)
        and (entry is None or other.entry_id != entry.entry_id)
        for other in hass.config_entries.async_entries(DOMAIN)
    )


# ---- repair issues -------------------------------------------------------------------


@callback
def async_check_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create or delete the profile's repair issues for missing entities."""
    flat: dict[str, Any] = {}
    for value in entry.options.values():
        if isinstance(value, Mapping):
            flat.update(value)
    speaker = entry.data.get(CONF_MEDIA_PLAYER)
    _set_issue(
        hass,
        entry,
        ISSUE_SPEAKER_MISSING,
        entity_missing(hass, speaker),
        speaker,
    )
    ma_player = flat.get(CONF_MA_PLAYER)
    _set_issue(
        hass,
        entry,
        ISSUE_MA_PLAYER_MISSING,
        entity_missing(hass, ma_player),
        ma_player,
    )


@callback
def _set_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    kind: str,
    missing: bool,
    entity_id: str | None,
) -> None:
    iid = issue_id(kind, entry.entry_id)
    if not missing:
        ir.async_delete_issue(hass, DOMAIN, iid)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        iid,
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR
        if kind == ISSUE_SPEAKER_MISSING
        else ir.IssueSeverity.WARNING,
        translation_key=kind,
        translation_placeholders={"profile": entry.title, "entity_id": entity_id or ""},
        # The fix flow (repairs.py) needs to know which profile to change.
        data={"entry_id": entry.entry_id, "kind": kind},
    )


@callback
def async_delete_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the profile's repair issues (it was unloaded or deleted)."""
    for kind in ISSUE_KINDS:
        ir.async_delete_issue(hass, DOMAIN, issue_id(kind, entry_id))


@callback
def referenced_ids(entry: ConfigEntry) -> set[str]:
    """Every entity ID the profile stores."""
    ids: set[str] = set()
    if speaker := entry.data.get(CONF_MEDIA_PLAYER):
        ids.add(speaker)
    for section, key in _SINGLE_OPTIONS:
        group = entry.options.get(section)
        if isinstance(group, Mapping) and group.get(key):
            ids.add(group[key])
    for section, key in _LIST_OPTIONS:
        group = entry.options.get(section)
        if isinstance(group, Mapping):
            ids.update(group.get(key) or [])
    return ids


@callback
def async_track_references(
    hass: HomeAssistant, entry: ConfigEntry
) -> Callable[[], None]:
    """Follow renames and keep the repair issues up to date. Returns the unsubscribe.

    Home Assistant's own state machine check waits until it has started; until
    then only renames are followed.
    """

    @callback
    def _registry_updated(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        data = event.data
        if data["action"] == "update" and "old_entity_id" in data:
            old_id = data["old_entity_id"]
            if old_id in referenced_ids(entry) and async_follow_rename(
                hass, entry, old_id, data["entity_id"]
            ):
                return
        if hass.state is CoreState.running:
            async_check_issues(hass, entry)

    @callback
    def _registry_filter(event_data: er.EventEntityRegistryUpdatedData) -> bool:
        """Only changes to an entity this profile stores (or used to)."""
        ids = referenced_ids(entry)
        return (
            event_data["entity_id"] in ids or event_data.get("old_entity_id") in ids  # type: ignore[operator]
        )

    @callback
    def _state_appeared_or_left(event: Event[EventStateChangedData]) -> None:
        if hass.state is CoreState.running:
            async_check_issues(hass, entry)

    @callback
    def _state_filter(event_data: EventStateChangedData) -> bool:
        """A stored entity's state was added or removed (not just changed).

        Deleting an entity removes its registry entry first and its state
        just after, so the check runs again when the state goes. Entities
        without a unique ID (YAML) only ever show up here.
        """
        return (
            event_data["old_state"] is None or event_data["new_state"] is None
        ) and event_data["entity_id"] in referenced_ids(entry)

    unsubs = [
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            _registry_updated,
            event_filter=_registry_filter,
        ),
        hass.bus.async_listen(
            EVENT_STATE_CHANGED,
            _state_appeared_or_left,
            event_filter=_state_filter,
        ),
    ]

    if hass.state is CoreState.running:
        async_check_issues(hass, entry)
    else:

        @callback
        def _started(_event: Event) -> None:
            unsubs.remove(unsub_started)
            async_check_issues(hass, entry)

        unsub_started = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _started
        )
        unsubs.append(unsub_started)

    @callback
    def _unsubscribe() -> None:
        for unsub in unsubs:
            unsub()
        unsubs.clear()

    return _unsubscribe
