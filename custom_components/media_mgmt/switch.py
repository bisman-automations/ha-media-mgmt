"""Switches: music filter and adult mode."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MediaMgmtConfigEntry
from .entity import MediaMgmtEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MediaMgmtConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    async_add_entities([MusicFilterSwitch(manager), AdultModeSwitch(manager)])


class MusicFilterSwitch(MediaMgmtEntity, SwitchEntity):
    """Skips blocked songs, artists, albums and apps."""

    def __init__(self, manager) -> None:
        super().__init__(manager, "music_filter")

    @property
    def is_on(self) -> bool:
        return self.manager.state.music_filter

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rules = self.manager.filter_rules()
        return {f"blocked_{kind}s": values for kind, values in rules.items()} | {
            "action": self.manager.filter_action
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._ensure_allowed()
        self.manager.set_music_filter(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._ensure_allowed()
        self.manager.set_music_filter(False)


class AdultModeSwitch(MediaMgmtEntity, SwitchEntity):
    """Lifts every rule for a while, then turns itself off."""

    def __init__(self, manager) -> None:
        super().__init__(manager, "adult_mode")

    @property
    def is_on(self) -> bool:
        return self.manager.adult_mode_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        until = self.manager.state.adult_mode_until_dt
        return {"until": until.isoformat() if until and self.is_on else None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._ensure_allowed()
        self.manager.set_adult_mode(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._ensure_allowed()
        self.manager.set_adult_mode(False)
