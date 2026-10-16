"""Config and options flow for Media Mgmt.

Everything here can also be changed in the Media Mgmt sidebar app, which
adds schedules, picking music to block from what's been played, and access.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    CONF_ADULT_MODE_DURATION,
    CONF_ANNOUNCE_ON_PLAYER,
    CONF_ANNOUNCE_PLAYERS,
    CONF_ANNOUNCE_TTS,
    CONF_BLOCKED_ALBUMS,
    CONF_BLOCKED_ARTISTS,
    CONF_BLOCKED_KEYWORDS,
    CONF_BLOCKED_SOURCES,
    CONF_BLOCKED_TRACKS,
    CONF_DAILY_BUDGET,
    CONF_FILTER_ACTION,
    CONF_LIMIT_ACTION,
    CONF_MAX_VOLUME,
    CONF_MEDIA_PLAYER,
    CONF_QUIET_WINDOWS,
    CONF_WARN_MINUTES,
    DEFAULT_ADULT_MODE_DURATION,
    DEFAULT_DAILY_BUDGET,
    DEFAULT_FILTER_ACTION,
    DEFAULT_LIMIT_ACTION,
    DEFAULT_MAX_VOLUME,
    DEFAULT_QUIET_WINDOWS,
    DEFAULT_WARN_MINUTES,
    DOMAIN,
    FILTER_ACTIONS,
    LIMIT_ACTIONS,
    SECTION_ANNOUNCE,
    SECTION_FILTER,
    SECTION_LISTENING,
    SECTION_VOLUME,
)
from .filters import clean_list
from .manager import flatten_options
from .quiet import parse_windows

LIST_KEYS = (CONF_BLOCKED_TRACKS, CONF_BLOCKED_ARTISTS, CONF_BLOCKED_ALBUMS, CONF_BLOCKED_SOURCES, CONF_BLOCKED_KEYWORDS)


def _number(min_: int, max_: int, unit: str | None = None, step: int = 1) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(min=min_, max=max_, step=step, mode=selector.NumberSelectorMode.BOX)
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _choice(options: list[str], key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, translation_key=key, mode=selector.SelectSelectorMode.LIST)
    )


def _lines(value: Any) -> str:
    return "\n".join(clean_list(value)) if not isinstance(value, str) else value


def _settings_schema(d: Mapping[str, Any]) -> vol.Schema:
    multiline = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
    listening = vol.Schema({
        vol.Required(CONF_DAILY_BUDGET, default=d.get(CONF_DAILY_BUDGET, DEFAULT_DAILY_BUDGET)): _number(0, 1440, "min"),
        vol.Required(CONF_WARN_MINUTES, default=d.get(CONF_WARN_MINUTES, DEFAULT_WARN_MINUTES)): _number(0, 60, "min"),
        vol.Optional(
            CONF_QUIET_WINDOWS, description={"suggested_value": d.get(CONF_QUIET_WINDOWS, DEFAULT_QUIET_WINDOWS)}
        ): selector.TextSelector(),
        vol.Required(CONF_LIMIT_ACTION, default=d.get(CONF_LIMIT_ACTION, DEFAULT_LIMIT_ACTION)): _choice(
            LIMIT_ACTIONS, CONF_LIMIT_ACTION
        ),
        vol.Required(
            CONF_ADULT_MODE_DURATION, default=d.get(CONF_ADULT_MODE_DURATION, DEFAULT_ADULT_MODE_DURATION)
        ): _number(5, 720, "min"),
    })
    music_filter: dict[Any, Any] = {
        vol.Optional(key, description={"suggested_value": _lines(d.get(key))}): multiline for key in LIST_KEYS
    }
    music_filter[vol.Required(CONF_FILTER_ACTION, default=d.get(CONF_FILTER_ACTION, DEFAULT_FILTER_ACTION))] = _choice(
        FILTER_ACTIONS, CONF_FILTER_ACTION
    )
    volume = vol.Schema({
        vol.Required(CONF_MAX_VOLUME, default=d.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=5, max=100, step=5, unit_of_measurement="%", mode=selector.NumberSelectorMode.SLIDER)
        ),
    })
    announce = vol.Schema({
        vol.Optional(CONF_ANNOUNCE_TTS, description={"suggested_value": d.get(CONF_ANNOUNCE_TTS)}): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="tts")
        ),
        vol.Required(CONF_ANNOUNCE_ON_PLAYER, default=bool(d.get(CONF_ANNOUNCE_ON_PLAYER, False))): selector.BooleanSelector(),
        vol.Optional(
            CONF_ANNOUNCE_PLAYERS, description={"suggested_value": d.get(CONF_ANNOUNCE_PLAYERS) or []}
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain=MP_DOMAIN, multiple=True)),
    })
    return vol.Schema({
        vol.Required(SECTION_LISTENING): section(listening),
        vol.Required(SECTION_FILTER): section(vol.Schema(music_filter), {"collapsed": True}),
        vol.Required(SECTION_VOLUME): section(volume, {"collapsed": True}),
        vol.Required(SECTION_ANNOUNCE): section(announce, {"collapsed": True}),
    })


def process_settings(user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate the settings form. Returns (options, errors)."""
    errors: dict[str, str] = {}
    listening = dict(user_input.get(SECTION_LISTENING, {}))
    try:
        windows = parse_windows(listening.get(CONF_QUIET_WINDOWS))
    except ValueError:
        errors["base"] = "bad_quiet_windows"
    else:
        listening[CONF_QUIET_WINDOWS] = ", ".join(w.format() for w in windows)
    for key in (CONF_DAILY_BUDGET, CONF_WARN_MINUTES, CONF_ADULT_MODE_DURATION):
        if key in listening:
            listening[key] = int(listening[key])
    listening.setdefault(CONF_LIMIT_ACTION, DEFAULT_LIMIT_ACTION)

    raw_filter = user_input.get(SECTION_FILTER, {})
    music_filter = {key: clean_list(raw_filter.get(key) or []) for key in LIST_KEYS}
    music_filter[CONF_FILTER_ACTION] = raw_filter.get(CONF_FILTER_ACTION) or DEFAULT_FILTER_ACTION

    volume = {CONF_MAX_VOLUME: int(user_input.get(SECTION_VOLUME, {}).get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME))}

    raw = user_input.get(SECTION_ANNOUNCE, {})
    announce = {
        CONF_ANNOUNCE_TTS: raw.get(CONF_ANNOUNCE_TTS) or None,
        CONF_ANNOUNCE_ON_PLAYER: bool(raw.get(CONF_ANNOUNCE_ON_PLAYER)),
        CONF_ANNOUNCE_PLAYERS: list(raw.get(CONF_ANNOUNCE_PLAYERS) or []),
    }
    if (announce[CONF_ANNOUNCE_PLAYERS] or announce[CONF_ANNOUNCE_ON_PLAYER]) and not announce[CONF_ANNOUNCE_TTS]:
        errors["base"] = "announce_needs_voice"

    return {
        SECTION_LISTENING: listening,
        SECTION_FILTER: music_filter,
        SECTION_VOLUME: volume,
        SECTION_ANNOUNCE: announce,
    }, errors


def default_options() -> dict[str, Any]:
    return process_settings({})[0]


class MediaMgmtConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._entity_id: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._entity_id = user_input[CONF_MEDIA_PLAYER]
            await self.async_set_unique_id(self._entity_id)
            self._abort_if_unique_id_configured()
            return await self.async_step_settings()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_MEDIA_PLAYER): selector.EntitySelector(selector.EntitySelectorConfig(domain=MP_DOMAIN))
            }),
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._entity_id is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            options, errors = process_settings(user_input)
            if not errors:
                state = self.hass.states.get(self._entity_id)
                return self.async_create_entry(
                    title=state.name if state else self._entity_id,
                    data={CONF_MEDIA_PLAYER: self._entity_id},
                    options=options,
                )
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(flatten_options(user_input or {})),
            errors=errors,
            description_placeholders={"entity": self._entity_id},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MediaMgmtOptionsFlow()


class MediaMgmtOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            options, errors = process_settings(user_input)
            if not errors:
                return self.async_create_entry(data=options)
        return self.async_show_form(
            step_id="init",
            data_schema=_settings_schema(flatten_options(dict(user_input or self.config_entry.options))),
            errors=errors,
        )
