"""The speaker: reads its media player's state and sends it commands.

Media Mgmt works through the integration that already runs the speaker, so
any media player Home Assistant has (Sonos, HomePod/AirPlay, Google Cast,
Music Assistant, Spotify, Alexa Media and others) can be managed.

A speaker can also have a Music Assistant "twin": the Music Assistant player
that streams to the same speaker. While the twin is playing, Media Mgmt reads
what's on from it and sends pause, skip and volume to it, because the
speaker's own integration can't skip or stop Music Assistant's stream.
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
        self.twin_id: str | None = None  # the Music Assistant player for this speaker
        self._unsub: CALLBACK_TYPE | None = None
        self._on_change: Callable[[], None] | None = None

    # ---- state ---------------------------------------------------------------

    @property
    def target(self) -> str:
        """The entity that's playing: the Music Assistant twin while it plays, else the speaker."""
        if self.twin_id and self.twin_id != self.entity_id:
            twin = self.hass.states.get(self.twin_id)
            if twin is not None and twin.state == "playing":
                return self.twin_id
            if twin is not None and twin.state == "paused" and self.state_of(self.entity_id) != "playing":
                own = self.hass.states.get(self.entity_id)
                # Paused in Music Assistant after it last played: resume there.
                if own is None or twin.last_changed >= own.last_changed:
                    return self.twin_id
        return self.entity_id

    def state_of(self, entity_id: str) -> str | None:
        st = self.hass.states.get(entity_id)
        return st.state if st else None

    @property
    def _state(self) -> State | None:
        return self.hass.states.get(self.target)

    @property
    def native_state(self) -> str | None:
        """The speaker's own state, whatever Music Assistant is doing."""
        return self.state_of(self.entity_id)

    @property
    def state(self) -> str | None:
        st = self._state
        return st.state if st else None

    @property
    def available(self) -> bool:
        return self.state not in (None, STATE_UNAVAILABLE, STATE_UNKNOWN)

    @property
    def via_twin(self) -> bool:
        """Is Music Assistant playing on this speaker right now?"""
        return self.target != self.entity_id

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
        st = self.hass.states.get(self.entity_id)
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

    def supports(self, feature: int, entity_id: str | None = None) -> bool:
        if entity_id is None:
            return bool(self.features & feature)
        st = self.hass.states.get(entity_id)
        return bool(int((st.attributes.get("supported_features") if st else 0) or 0) & feature)

    @property
    def source_list(self) -> list[str]:
        """The speaker's own favourites, stations and inputs (Sonos favourites, say)."""
        st = self.hass.states.get(self.entity_id)
        return [str(s) for s in (st.attributes.get("source_list") if st else None) or []]

    @property
    def platform(self) -> str | None:
        entity = er.async_get(self.hass).async_get(self.entity_id)
        return entity.platform if entity else None

    @property
    def is_music_assistant(self) -> bool:
        return self.platform == MUSIC_ASSISTANT_DOMAIN and self.hass.services.has_service(
            MUSIC_ASSISTANT_DOMAIN, "play_media"
        )

    @property
    def ma_entity_id(self) -> str | None:
        """The Music Assistant player to play through: the speaker itself, or its twin."""
        if not self.hass.services.has_service(MUSIC_ASSISTANT_DOMAIN, "play_media"):
            return None
        if self.platform == MUSIC_ASSISTANT_DOMAIN:
            return self.entity_id
        return self.twin_id

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
            "music_assistant": self.ma_entity_id is not None,
        }

    # ---- listening -----------------------------------------------------------

    @callback
    def async_start(self, on_change: Callable[[], None]) -> None:
        self._on_change = on_change
        self._track()

    @callback
    def _track(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._on_change is None:
            return
        on_change = self._on_change

        @callback
        def _changed(_event: Event) -> None:
            on_change()

        ids = [self.entity_id] + ([self.twin_id] if self.twin_id and self.twin_id != self.entity_id else [])
        self._unsub = async_track_state_change_event(self.hass, ids, _changed)

    @callback
    def set_twin(self, twin_id: str | None) -> bool:
        """Follow a different Music Assistant player. Returns True if it changed."""
        if twin_id == self.entity_id:
            twin_id = None
        if twin_id == self.twin_id:
            return False
        self.twin_id = twin_id
        self._track()
        return True

    @callback
    def async_stop(self) -> None:
        self._on_change = None
        if self._unsub:
            self._unsub()
            self._unsub = None

    # ---- commands ------------------------------------------------------------

    async def _call(
        self, service: str, data: dict[str, Any] | None = None, *, domain: str = MP_DOMAIN, target: str | None = None
    ) -> bool:
        entity_id = target or self.target
        try:
            await self.hass.services.async_call(
                domain, service, {ATTR_ENTITY_ID: entity_id, **(data or {})}, blocking=True
            )
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("Media Mgmt: %s.%s on %s failed: %s", domain, service, entity_id, err)
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

    async def async_set_volume(self, level: float, *, target: str | None = None) -> bool:
        return await self._call("volume_set", {"volume_level": round(max(0.0, min(1.0, level)), 3)}, target=target)

    async def async_play(self) -> bool:
        return await self._call("media_play")

    async def async_play_media(self, content_id: str, content_type: str, *, enqueue: str | None = None) -> bool:
        """Play on the speaker's own integration."""
        data: dict[str, Any] = {"media_content_id": content_id, "media_content_type": content_type}
        if enqueue and self.supports(F.MEDIA_ENQUEUE, self.entity_id):
            data["enqueue"] = enqueue
        return await self._call("play_media", data, target=self.entity_id)

    async def async_music_assistant(
        self, media_id: str | list[str], media_type: str, *, radio: bool = False, enqueue: str = "replace"
    ) -> bool:
        """Play through Music Assistant, on the speaker or its twin."""
        if (target := self.ma_entity_id) is None:
            return False
        data: dict[str, Any] = {"media_id": media_id, "media_type": media_type, "enqueue": enqueue}
        if radio:
            data["radio_mode"] = True
        return await self._call("play_media", data, domain=MUSIC_ASSISTANT_DOMAIN, target=target)

    async def async_select_source(self, source: str) -> bool:
        return await self._call("select_source", {"source": source}, target=self.entity_id)

    async def async_shuffle(self, shuffle: bool, *, target: str | None = None) -> bool:
        return self.supports(F.SHUFFLE_SET, target) and await self._call("shuffle_set", {"shuffle": shuffle}, target=target)

    async def async_repeat(self, repeat: str, *, target: str | None = None) -> bool:
        return self.supports(F.REPEAT_SET, target) and await self._call("repeat_set", {"repeat": repeat}, target=target)

    async def async_turn_on(self) -> bool:
        return self.supports(F.TURN_ON, self.entity_id) and await self._call("turn_on", target=self.entity_id)
