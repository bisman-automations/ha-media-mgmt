"""Buttons: block the song or artist playing now, and play a saved artist, for a dashboard.

The Play buttons (one per saved artist) start turned off; turn on the ones
you want on a dashboard in the speaker's device page.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MediaMgmtConfigEntry, current_value
from .const import DOMAIN, SIGNAL_ARTISTS_UPDATED
from .entity import MediaMgmtEntity
from .saved import async_play_request, get_saved


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MediaMgmtConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    async_add_entities([BlockButton(manager, "track"), BlockButton(manager, "artist")])

    buttons: dict[str, PlayArtistButton] = {}

    @callback
    def _sync() -> None:
        """Add a button for each new saved artist; remove the ones for deleted artists."""
        artists = {a.id: a for a in get_saved(hass).artists}
        new = [
            PlayArtistButton(manager, a.id, a.name)
            for a_id, a in artists.items()
            if a_id not in buttons
        ]
        for button in new:
            buttons[button.artist_id] = button
        if new:
            async_add_entities(new)
        registry = er.async_get(hass)
        for artist_id in [i for i in buttons if i not in artists]:
            button = buttons.pop(artist_id)
            if entity_id := registry.async_get_entity_id(
                "button", DOMAIN, button.unique_id
            ):
                registry.async_remove(entity_id)
        for artist_id, button in buttons.items():
            button.rename(artists[artist_id].name)

    _sync()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_ARTISTS_UPDATED, _sync))


class BlockButton(MediaMgmtEntity, ButtonEntity):
    def __init__(self, manager, kind: str) -> None:
        super().__init__(manager, f"block_current_{kind}")
        self._kind = kind

    async def async_press(self) -> None:
        await self._ensure_allowed()
        user = (
            await self.hass.auth.async_get_user(self._context.user_id)
            if self._context and self._context.user_id
            else None
        )
        value = current_value(self.manager, self._kind)
        self.manager.update_filter(
            self._kind, value, add=True, by=user.name if user else None
        )


class PlayArtistButton(MediaMgmtEntity, ButtonEntity):
    """Play a saved artist on this speaker. Rules still apply."""

    _attr_entity_registry_enabled_default = False

    def __init__(self, manager, artist_id: str, name: str) -> None:
        super().__init__(manager, f"play_artist_{artist_id}")
        self._attr_translation_key = "play_saved_artist"
        self._attr_translation_placeholders = {"artist": name}
        self.artist_id = artist_id

    @callback
    def rename(self, name: str) -> None:
        if self._attr_translation_placeholders.get("artist") != name:
            self._attr_translation_placeholders = {"artist": name}
            if self.hass is not None and self.entity_id:
                self.async_write_ha_state()

    async def async_press(self) -> None:
        # Like pressing play on the speaker: open to everyone, and every rule applies.
        user = (
            await self.hass.auth.async_get_user(self._context.user_id)
            if self._context and self._context.user_id
            else None
        )
        result = await async_play_request(
            self.hass,
            self.artist_id,
            profile_id=self.manager.entry.entry_id,
            by=user.name if user else None,
        )
        if not result.ok:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="play_failed",
                translation_placeholders={"message": result.message},
            )
