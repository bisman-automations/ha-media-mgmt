"""Spoken warnings: "5 minutes of music left", "Music time is up".

Said on the speaker itself as an announcement (the music ducks and comes
back), where the speaker supports announcements, and on any other speakers
picked, with a text-to-speech voice.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from urllib.parse import quote

from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from .state import REASON_BUDGET, REASON_MANUAL, REASON_QUIET

_LOGGER = logging.getLogger(__name__)


def warning_message(minutes: int) -> str:
    return f"{minutes} minute{'' if minutes == 1 else 's'} of music left."


def stopping_message(reason: str | None, window: str | None = None) -> str:
    if reason == REASON_BUDGET:
        return "Music time is up for today. The music is stopping now."
    if reason == REASON_QUIET:
        return f"It's {window.lower()} time. The music is stopping now." if window else "It's quiet time. The music is stopping now."
    if reason == REASON_MANUAL:
        return "A parent stopped the music."
    return "The music is stopping now."


class Announcer:
    def __init__(
        self,
        hass: HomeAssistant,
        *,
        tts_entity: str | None,
        player: str | None,
        on_player: bool,
        players: list[str],
        player_can_announce: Callable[[], bool],
    ) -> None:
        self.hass = hass
        self.tts_entity = tts_entity
        self._player = player if on_player else None
        self._can_announce = player_can_announce
        self.players = [p for p in players if p != player]

    @property
    def player(self) -> str | None:
        """The speaker itself, when it can announce over its music."""
        return self._player if self._player and self._can_announce() else None

    @property
    def enabled(self) -> bool:
        return bool(self.tts_entity and (self.player or self.players))

    def announce(self, message: str) -> bool:
        """Say it. Returns True if anything was said."""
        if not self.enabled:
            return False
        if self.player:
            self.hass.async_create_task(self._on_player(message))
        if self.players:
            self.hass.async_create_task(self._speak(message))
        return True

    async def _on_player(self, message: str) -> None:
        url = f"media-source://tts/{self.tts_entity}?message={quote(message)}"
        try:
            await self.hass.services.async_call(
                MP_DOMAIN,
                "play_media",
                {
                    ATTR_ENTITY_ID: self.player,
                    "media_content_id": url,
                    "media_content_type": "music",
                    "announce": True,
                },
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - a warning failing mustn't stop enforcement
            _LOGGER.warning("Media Mgmt couldn't announce on %s: %s", self.player, err)

    async def _speak(self, message: str) -> None:
        try:
            await self.hass.services.async_call(
                "tts",
                "speak",
                {ATTR_ENTITY_ID: self.tts_entity, "media_player_entity_id": self.players, "message": message},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Media Mgmt couldn't speak a warning: %s", err)
