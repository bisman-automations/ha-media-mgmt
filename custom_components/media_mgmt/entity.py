"""Shared entity base for Media Mgmt."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .access import async_ensure_allowed
from .const import DOMAIN, SIGNAL_UPDATED
from .manager import MediaManager


class MediaMgmtEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: MediaManager, key: str) -> None:
        self.manager = manager
        entry = manager.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        # The profile's device shares the speaker's identifiers (set in
        # _link_devices), so they show under each other's Linked devices.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Media Mgmt — {entry.title}",
            manufacturer="Media Mgmt",
            model="Speaker profile",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def _ensure_allowed(self) -> None:
        """Only admins and allowed parents may change Media Mgmt from the UI."""
        await async_ensure_allowed(self.hass, self._context)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATED.format(self.manager.entry.entry_id),
                self.async_write_ha_state,
            )
        )
