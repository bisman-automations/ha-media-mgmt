"""Selects: the speaker's mode (enforced / monitor only / paused), and Play artist.

Play artist lists the home's saved artists; picking one plays it on this
speaker. It starts turned off; turn it on in the speaker's device page.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MediaMgmtConfigEntry
from .const import DOMAIN, SIGNAL_ARTISTS_UPDATED
from .entity import MediaMgmtEntity
from .saved import async_play_request, get_saved
from .state import MODES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MediaMgmtConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [ModeSelect(entry.runtime_data), PlayArtistSelect(entry.runtime_data)]
    )


class ModeSelect(MediaMgmtEntity, SelectEntity):
    _attr_options = MODES

    def __init__(self, manager) -> None:
        super().__init__(manager, "mode")

    @property
    def current_option(self) -> str:
        return self.manager.state.mode

    async def async_select_option(self, option: str) -> None:
        await self._ensure_allowed()
        self.manager.set_mode(option)


class PlayArtistSelect(MediaMgmtEntity, SelectEntity):
    """Pick a saved artist to play it on this speaker. Rules still apply."""

    _attr_entity_registry_enabled_default = False

    def __init__(self, manager) -> None:
        super().__init__(manager, "play_artist")
        self._last: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ARTISTS_UPDATED, self._artists_changed
            )
        )

    @callback
    def _artists_changed(self) -> None:
        self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        return [a.name for a in get_saved(self.hass).artists] if self.hass else []

    @property
    def current_option(self) -> str | None:
        return self._last if self._last in self.options else None

    async def async_select_option(self, option: str) -> None:
        # Like pressing play on the speaker: open to everyone, and every rule applies.
        user = (
            await self.hass.auth.async_get_user(self._context.user_id)
            if self._context and self._context.user_id
            else None
        )
        result = await async_play_request(
            self.hass,
            option,
            profile_id=self.manager.entry.entry_id,
            by=user.name if user else None,
        )
        if not result.ok:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="play_failed",
                translation_placeholders={"message": result.message},
            )
        self._last = option
        self.async_write_ha_state()
