"""The speaker: reads its media player's state and sends it commands.

Media Mgmt works through the integration that already runs the speaker, so
any media player Home Assistant has (Sonos, HomePod/AirPlay, Google Cast,
Music Assistant, Spotify, Alexa Media and others) can be managed.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.components.media_player import (
    DOMAIN as MP_DOMAIN,
    MediaPlayerEntityFeature as F,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ACTION_PAUSE,
    ACTION_SKIP,
    ACTION_STOP,
    ACTION_TURN_OFF,
    MUSIC_ASSISTANT_DOMAIN,
)
from .media import media_from

_LOGGER = logging.getLogger(__name__)

OFF_STATES = ("off", "standby")


class Player:
    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        self.hass = hass
        self.entity_id = entity_id
        self._unsub: CALLBACK_TYPE | None = None

    # ---- state ---------------------------------------------------------------

    @property
    def _state(self) -> State | None:
        return self.hass.states.get(self.entity_id)

    @property
    def state(self) -> str | None:
        st = self._state
        return st.state if st else None

    @property
    def available(self) -> bool:
        return self.state not in (None, STATE_UNAVAILABLE, STATE_UNKNOWN)

    @property
    def is_playing(self) -> bool:
        return self.state == "playing"

    @property
    def is_on(self) -> bool | None:
        if not self.available:
            return None
        return self.state not in OFF_STATES

    @property
    def attributes(self) -> dict[str, Any]:
        st = self._state
        return dict(st.attributes) if st else {}

    @property
    def name(self) -> str:
        st = self._state
        return st.name if st else self.entity_id

    @property
    def media(self) -> dict[str, Any] | None:
        return media_from(self.state, self.attributes)

    @property
    def volume(self) -> float | None:
        value = self.attributes.get("volume_level")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def features(self) -> int:
        return int(self.attributes.get("supported_features") or 0)

    def supports(self, feature: int) -> bool:
        return bool(self.features & feature)

    @property
    def source_list(self) -> list[str]:
        return [str(s) for s in self.attributes.get("source_list") or []]

    @property
    def platform(self) -> str | None:
        entity = er.async_get(self.hass).async_get(self.entity_id)
        return entity.platform if entity else None

    @property
    def is_music_assistant(self) -> bool:
        return self.platform == MUSIC_ASSISTANT_DOMAIN and self.hass.services.has_service(
            MUSIC_ASSISTANT_DOMAIN, "play_media"
        )

    def capabilities(self) -> dict[str, bool]:
        return {
            "pause": self.supports(F.PAUSE),
            "play": self.supports(F.PLAY),
            "stop": self.supports(F.STOP),
            "next": self.supports(F.NEXT_TRACK),
            "previous": self.supports(F.PREVIOUS_TRACK),
            "volume": self.supports(F.VOLUME_SET),
            "turn_off": self.supports(F.TURN_OFF),
            "play_media": self.supports(F.PLAY_MEDIA),
            "source": self.supports(F.SELECT_SOURCE),
            "shuffle": self.supports(F.SHUFFLE_SET),
            "repeat": self.supports(F.REPEAT_SET),
            "announce": self.supports(F.MEDIA_ANNOUNCE),
            "music_assistant": self.is_music_assistant,
        }

    # ---- listening -----------------------------------------------------------

    @callback
    def async_start(self, on_change: Callable[[], None]) -> None:
        @callback
        def _changed(_event: Event) -> None:
            on_change()

        self._unsub = async_track_state_change_event(self.hass, [self.entity_id], _changed)

    @callback
    def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    # ---- commands ------------------------------------------------------------

    async def _call(self, service: str, data: dict[str, Any] | None = None, *, domain: str = MP_DOMAIN) -> bool:
        try:
            await self.hass.services.async_call(
                domain, service, {ATTR_ENTITY_ID: self.entity_id, **(data or {})}, blocking=True
            )
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("Media Mgmt: %s.%s on %s failed: %s", domain, service, self.entity_id, err)
            return False
        return True

    def resolve_action(self, action: str) -> str:
        """The action this speaker can actually do, falling back as needed."""
        order = {
            ACTION_SKIP: [ACTION_SKIP, ACTION_PAUSE, ACTION_STOP, ACTION_TURN_OFF],
            ACTION_PAUSE: [ACTION_PAUSE, ACTION_STOP, ACTION_TURN_OFF],
            ACTION_STOP: [ACTION_STOP, ACTION_PAUSE, ACTION_TURN_OFF],
            ACTION_TURN_OFF: [ACTION_TURN_OFF, ACTION_PAUSE, ACTION_STOP],
        }.get(action, [ACTION_PAUSE, ACTION_STOP, ACTION_TURN_OFF])
        feature = {ACTION_SKIP: F.NEXT_TRACK, ACTION_PAUSE: F.PAUSE, ACTION_STOP: F.STOP, ACTION_TURN_OFF: F.TURN_OFF}
        for candidate in order:
            if self.supports(feature[candidate]):
                return candidate
        # Nothing reported: try what was asked; the integration may still accept it.
        return action

    async def async_do(self, action: str) -> bool:
        service = {
            ACTION_SKIP: "media_next_track",
            ACTION_PAUSE: "media_pause",
            ACTION_STOP: "media_stop",
            ACTION_TURN_OFF: "turn_off",
        }[action]
        return await self._call(service)

    async def async_set_volume(self, level: float) -> bool:
        return await self._call("volume_set", {"volume_level": round(max(0.0, min(1.0, level)), 3)})

    async def async_play(self) -> bool:
        return await self._call("media_play")

    async def async_play_media(self, content_id: str, content_type: str, *, enqueue: str | None = None) -> bool:
        data: dict[str, Any] = {"media_content_id": content_id, "media_content_type": content_type}
        if enqueue and self.supports(F.MEDIA_ENQUEUE):
            data["enqueue"] = enqueue
        return await self._call("play_media", data)

    async def async_music_assistant(self, media_id: str, media_type: str, *, radio: bool = False) -> bool:
        data: dict[str, Any] = {"media_id": media_id, "media_type": media_type, "enqueue": "replace"}
        if radio:
            data["radio_mode"] = True
        return await self._call("play_media", data, domain=MUSIC_ASSISTANT_DOMAIN)

    async def async_select_source(self, source: str) -> bool:
        return await self._call("select_source", {"source": source})

    async def async_shuffle(self, shuffle: bool) -> bool:
        return self.supports(F.SHUFFLE_SET) and await self._call("shuffle_set", {"shuffle": shuffle})

    async def async_repeat(self, repeat: str) -> bool:
        return self.supports(F.REPEAT_SET) and await self._call("repeat_set", {"repeat": repeat})

    async def async_turn_on(self) -> bool:
        return self.supports(F.TURN_ON) and await self._call("turn_on")
