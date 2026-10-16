"""Buttons: block the song or artist playing now, for a dashboard."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MediaMgmtConfigEntry, current_value
from .entity import MediaMgmtEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: MediaMgmtConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager = entry.runtime_data
    async_add_entities([BlockButton(manager, "track"), BlockButton(manager, "artist")])


class BlockButton(MediaMgmtEntity, ButtonEntity):
    def __init__(self, manager, kind: str) -> None:
        super().__init__(manager, f"block_current_{kind}")
        self._kind = kind

    async def async_press(self) -> None:
        await self._ensure_allowed()
        user = await self.hass.auth.async_get_user(self._context.user_id) if self._context and self._context.user_id else None
        value = current_value(self.manager, self._kind)
        self.manager.update_filter(self._kind, value, add=True, by=user.name if user else None)
