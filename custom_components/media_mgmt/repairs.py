"""Fix flows for Media Mgmt's repair issues (Settings → Repairs → Fix).

The issues are raised in references.py when an entity a profile stores is
deleted from Home Assistant:

- ``speaker_missing``: the speaker the profile manages. Fix by picking the
  speaker to manage now; the profile keeps its rules, schedules and history
  and reloads with it.
- ``music_assistant_player_missing``: the Music Assistant player picked by
  hand under Playback. Fix by picking another one, or leave it empty to let
  Media Mgmt find the speaker's Music Assistant player itself again.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.components.repairs import (
    ConfirmRepairFlow,
    RepairsFlow,
    RepairsFlowResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir, selector

from .const import (
    CONF_MA_PLAYER,
    CONF_MEDIA_PLAYER,
    DOMAIN,
    MUSIC_ASSISTANT_DOMAIN,
    SECTION_PLAYBACK,
)
from .references import (
    ISSUE_MA_PLAYER_MISSING,
    ISSUE_SPEAKER_MISSING,
    issue_id,
    speaker_taken,
)
from .schema import vol


class _ProfileRepairFlow(RepairsFlow):
    """A fix flow for one profile's issue; the issue's data names the profile."""

    def __init__(self, entry: ConfigEntry, kind: str) -> None:
        self._entry = entry
        self._kind = kind

    def _placeholders(self, entity_id: str | None) -> dict[str, str]:
        return {"profile": self._entry.title, "entity_id": entity_id or ""}

    def _done(self) -> RepairsFlowResult:
        # The issue is cleared now, rather than when the reload or the next
        # check gets to it, so the Repairs list doesn't still show it.
        ir.async_delete_issue(
            self.hass, DOMAIN, issue_id(self._kind, self._entry.entry_id)
        )
        return self.async_create_entry(data={})


class SpeakerMissingRepairFlow(_ProfileRepairFlow):
    """Pick the speaker the profile manages now."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        return await self.async_step_pick_speaker()

    async def async_step_pick_speaker(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        entry = self._entry
        old_id = entry.data.get(CONF_MEDIA_PLAYER)
        errors: dict[str, str] = {}
        if user_input is not None:
            new_id = user_input[CONF_MEDIA_PLAYER]
            if speaker_taken(self.hass, entry, new_id):
                errors[CONF_MEDIA_PLAYER] = "speaker_taken"
            else:
                # The update listener reloads the profile with the new speaker.
                self.hass.config_entries.async_update_entry(
                    entry,
                    unique_id=new_id,
                    data={**entry.data, CONF_MEDIA_PLAYER: new_id},
                )
                return self._done()
        return self.async_show_form(
            step_id="pick_speaker",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MEDIA_PLAYER): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain=MP_DOMAIN)
                    )
                }
            ),
            errors=errors,
            description_placeholders=self._placeholders(old_id),
        )


class MusicAssistantPlayerMissingRepairFlow(_ProfileRepairFlow):
    """Pick another Music Assistant player, or let Media Mgmt find it."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        return await self.async_step_pick_player()

    async def async_step_pick_player(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        entry = self._entry
        old_id = (entry.options.get(SECTION_PLAYBACK) or {}).get(CONF_MA_PLAYER)
        if user_input is not None:
            options = {
                key: dict(value) if isinstance(value, dict) else value
                for key, value in entry.options.items()
            }
            playback = options.setdefault(SECTION_PLAYBACK, {})
            # Empty: Media Mgmt finds the speaker's Music Assistant player itself.
            playback[CONF_MA_PLAYER] = user_input.get(CONF_MA_PLAYER) or None
            # The update listener applies the setting without a reload.
            self.hass.config_entries.async_update_entry(entry, options=options)
            return self._done()
        return self.async_show_form(
            step_id="pick_player",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_MA_PLAYER): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=MP_DOMAIN, integration=MUSIC_ASSISTANT_DOMAIN
                        )
                    )
                }
            ),
            description_placeholders=self._placeholders(old_id),
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """The fix flow for a Media Mgmt repair issue."""
    entry = (
        hass.config_entries.async_get_entry(str(data["entry_id"]))
        if data and data.get("entry_id")
        else None
    )
    kind = str((data or {}).get("kind") or "")
    if entry is not None and entry.domain == DOMAIN:
        if kind == ISSUE_SPEAKER_MISSING:
            return SpeakerMissingRepairFlow(entry, kind)
        if kind == ISSUE_MA_PLAYER_MISSING:
            return MusicAssistantPlayerMissingRepairFlow(entry, kind)
    # The profile was deleted since: nothing to change, just confirm.
    return ConfirmRepairFlow()
