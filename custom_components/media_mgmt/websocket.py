"""Websocket API used by the Media Mgmt sidebar app.

Every setting can be read and changed here, so the sidebar app is the one
place to manage a speaker: limits, blocked music, volume, warnings and
schedules.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import wraps
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .access import get_access
from .activity import merge_series, summarize
from .const import (
    BLOCK_KINDS,
    CONF_ADULT_MODE_DURATION,
    CONF_ANNOUNCE_ON_PLAYER,
    CONF_ANNOUNCE_PLAYERS,
    CONF_ANNOUNCE_TTS,
    CONF_DAILY_BUDGET,
    CONF_FILTER_ACTION,
    CONF_LIMIT_ACTION,
    CONF_MA_PLAYER,
    CONF_MAX_VOLUME,
    CONF_QUIET_WINDOWS,
    CONF_WARN_MINUTES,
    DOMAIN,
    FILTER_ACTIONS,
    LIMIT_ACTIONS,
    SECTION_ANNOUNCE,
    SECTION_FILTER,
    SECTION_LISTENING,
    SECTION_PLAYBACK,
    SECTION_VOLUME,
    SIGNAL_ANY_UPDATED,
    SIGNAL_ARTISTS_UPDATED,
)
from .filters import clean_list
from .manager import MediaManager
from .media import split_key, track_key
from .quiet import parse_windows
from .schedules import PLAY_KINDS
from .state import MODES

ACTIONS = [
    "grant_extension",
    "force_block",
    "unblock",
    "reset_usage",
    "set_mode",
    "set_adult_mode",
    "set_music_filter",
    "set_sleep_timer",
    "cancel_sleep_timer",
]

# Settings the sidebar app may change, and the option section each lives in.
SETTINGS: dict[str, tuple[str, Any]] = {
    CONF_DAILY_BUDGET: (SECTION_LISTENING, vol.All(int, vol.Range(min=0, max=1440))),
    CONF_WARN_MINUTES: (SECTION_LISTENING, vol.All(int, vol.Range(min=0, max=60))),
    CONF_QUIET_WINDOWS: (SECTION_LISTENING, str),
    CONF_ADULT_MODE_DURATION: (SECTION_LISTENING, vol.All(int, vol.Range(min=5, max=720))),
    CONF_LIMIT_ACTION: (SECTION_LISTENING, vol.In(LIMIT_ACTIONS)),
    CONF_FILTER_ACTION: (SECTION_FILTER, vol.In(FILTER_ACTIONS)),
    CONF_MAX_VOLUME: (SECTION_VOLUME, vol.All(int, vol.Range(min=5, max=100))),
    CONF_ANNOUNCE_TTS: (SECTION_ANNOUNCE, vol.Any(None, str)),
    CONF_ANNOUNCE_ON_PLAYER: (SECTION_ANNOUNCE, bool),
    CONF_ANNOUNCE_PLAYERS: (SECTION_ANNOUNCE, [str]),
    CONF_MA_PLAYER: (SECTION_PLAYBACK, vol.Any(None, str)),
}


@callback
def async_register(hass: HomeAssistant) -> None:
    for command in (
        ws_profiles,
        ws_activity,
        ws_analytics,
        ws_history,
        ws_settings_get,
        ws_settings_set,
        ws_filter_update,
        ws_filter_set,
        ws_schedule_save,
        ws_schedule_delete,
        ws_schedule_run,
        ws_action,
        ws_subscribe,
        ws_access_me,
        ws_access_get,
        ws_access_set,
        ws_speakers_candidates,
        ws_speakers_add,
        ws_speakers_remove,
        ws_artists_list,
        ws_artists_search,
        ws_artists_save,
        ws_artists_delete,
        ws_artists_play,
    ):
        websocket_api.async_register_command(hass, command)


# ---- helpers -------------------------------------------------------------------


def require_access(func):
    """Only admins and the parents an admin allowed may use the sidebar app."""

    @wraps(func)
    def with_access(hass: HomeAssistant, connection, msg) -> None:
        if not get_access(hass).allows(connection.user):
            raise Unauthorized
        return func(hass, connection, msg)

    return with_access


def _managers(hass: HomeAssistant) -> list[MediaManager]:
    return sorted(
        (e.runtime_data for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED),
        key=lambda m: m.name.casefold(),
    )


def _manager(hass: HomeAssistant, connection, msg) -> MediaManager | None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "not_found", "Media Mgmt profile not found or not loaded")
        return None
    return entry.runtime_data


def _by(connection) -> str | None:
    return connection.user.name if connection.user else None


def _ranked(values: dict[str, int], limit: int = 8) -> list[dict[str, Any]]:
    return [{"name": k, "seconds": v} for k, v in sorted(values.items(), key=lambda kv: kv[1], reverse=True)[:limit]]


def schedule_summary(manager: MediaManager) -> list[dict[str, Any]]:
    now = dt_util.now()
    active = manager.decision.schedule
    result = []
    for sched in manager.schedules:
        nxt = sched.next_run(now)
        result.append({
            **sched.as_dict(),
            "next_run": nxt.isoformat() if nxt else None,
            "active": active == sched.name,
        })
    return result


def ma_link_summary(manager: MediaManager) -> dict[str, Any]:
    """The speaker's Music Assistant player, how it was found, and whether it's playing."""
    link = manager.ma_link
    state = manager.hass.states.get(link.entity_id) if link.entity_id else None
    return {
        **link.as_dict(),
        "name": state.name if state else None,
        "state": state.state if state else None,
        "playing_through": manager.player.via_twin,
        "available": manager.player.ma_entity_id is not None,
        "manual": manager.options.get(CONF_MA_PLAYER),
    }


def profile_summary(manager: MediaManager) -> dict[str, Any]:
    s = manager.state
    d = manager.decision
    player = manager.player
    media = player.media
    rule = manager.blocked_rule(media) if media else None
    until = s.adult_mode_until_dt if manager.adult_mode_active else None
    return {
        "entry_id": manager.entry.entry_id,
        "name": manager.name,
        "entity_id": manager.entity_id,
        "player_state": player.state,
        "is_on": player.is_on,
        "media": media,
        "track_key": track_key(media),
        "blocked_by": {"kind": rule[0], "rule": rule[1]} if rule else None,
        "volume": round(player.volume * 100) if player.volume is not None else None,
        "capabilities": player.capabilities(),
        "ma_link": ma_link_summary(manager),
        "state": d.state,
        "reason": d.reason,
        "quiet_window": d.quiet_window,
        "schedule": d.schedule,
        "remaining_seconds": d.remaining_seconds,
        "mode": s.mode,
        "music_filter": s.music_filter,
        "force_block": s.force_block,
        "adult_mode_until": until.isoformat() if until else None,
        "adult_mode_duration": manager.adult_mode_duration,
        "used_seconds": s.used_seconds,
        "schedule_seconds": s.schedule_seconds,
        "budget_minutes": manager.daily_budget,
        "extension_minutes": s.extension_minutes,
        "warn_minutes": manager.warn_minutes,
        "max_volume": manager.max_volume,
        # The cap right now: lower while a playing schedule limits the volume.
        "volume_cap": manager.volume_cap,
        "volume_limit_schedule": (sched.name if (sched := manager.volume_limit_schedule()) else None),
        "blocked_count": s.blocked_count,
        "last_blocked": s.last_blocked,
        "last_blocked_at": s.last_blocked_at,
        "plays": s.plays,
        "top_artists": _ranked(s.artist_seconds, 5),
        "sleep_until": s.sleep_until,
        "sleep_fade": s.sleep_fade,
        "quiet_windows": [w.format() for w in manager.quiet_windows],
        "filter": manager.filter_rules(),
        "filter_action": manager.filter_action,
        "schedules": schedule_summary(manager),
        "entities": [
            {"entity_id": e.entity_id, "key": e.translation_key or e.domain}
            for e in er.async_entries_for_config_entry(er.async_get(manager.hass), manager.entry.entry_id)
            if not e.disabled
        ],
    }


def _local_day_bounds(day: date) -> tuple[datetime, datetime]:
    return dt_util.start_of_local_day(day), dt_util.start_of_local_day(day + timedelta(days=1))


def _is_blocked(manager: MediaManager, item: dict[str, Any]) -> dict[str, str] | None:
    rule = manager.filter.match(item)
    return {"kind": rule[0], "rule": rule[1]} if rule else None


# ---- read commands -------------------------------------------------------------


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/profiles"})
@require_access
@callback
def ws_profiles(hass: HomeAssistant, connection, msg) -> None:
    connection.send_result(
        msg["id"],
        {"profiles": [profile_summary(m) for m in _managers(hass)], "now": dt_util.utcnow().isoformat()},
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/activity", vol.Required("entry_id"): str, vol.Optional("date"): str}
)
@require_access
@callback
def ws_activity(hass: HomeAssistant, connection, msg) -> None:
    if (manager := _manager(hass, connection, msg)) is None:
        return
    try:
        day = date.fromisoformat(msg["date"]) if msg.get("date") else dt_util.now().date()
    except ValueError:
        connection.send_error(msg["id"], "invalid_format", "date must be YYYY-MM-DD")
        return
    start, end = _local_day_bounds(day)
    log = manager.activity
    segments = log.listening_segments(start, end, dt_util.utcnow())
    connection.send_result(
        msg["id"],
        {
            "entry_id": manager.entry.entry_id,
            "date": day.isoformat(),
            "today": dt_util.now().date().isoformat(),
            "first_date": log.first_day,
            "events": list(reversed(log.events_between(start, end))),
            "segments": segments,
            "listening_seconds": sum(s["seconds"] for s in segments),
            "totals": log.daily.get(day.isoformat()),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/analytics",
        vol.Optional("entry_id"): str,
        vol.Optional("days", default=7): vol.All(int, vol.Range(min=1, max=366)),
    }
)
@require_access
@callback
def ws_analytics(hass: HomeAssistant, connection, msg) -> None:
    """One speaker's analytics, or every speaker added together."""
    today = dt_util.now().date()
    if "entry_id" in msg:
        if (manager := _manager(hass, connection, msg)) is None:
            return
        managers = [manager]
    else:
        managers = _managers(hass)
    per_speaker = [(m, m.activity.daily_series(today, msg["days"])) for m in managers]
    series = per_speaker[0][1] if len(per_speaker) == 1 else merge_series([s for _, s in per_speaker])
    summary = summarize(series)
    if len(managers) == 1:
        for item in summary["top_tracks"]:
            item["blocked"] = _is_blocked(managers[0], _track_item(item["key"]))
        for item in summary["top_artists"]:
            item["blocked"] = _is_blocked(managers[0], {"title": "", "artist": item["artist"]})
    connection.send_result(
        msg["id"],
        {
            "entry_id": msg.get("entry_id"),
            "days": series,
            "range": msg["days"],
            "summary": summary,
            "speakers": [
                {"entry_id": m.entry.entry_id, "name": m.name, "seconds": sum(d["used_seconds"] + d.get("schedule_seconds", 0) for d in s)}
                for m, s in per_speaker
            ],
        },
    )


def _track_item(key: str) -> dict[str, Any]:
    title, artist = split_key(key)
    return {"title": title, "artist": artist}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/history",
        vol.Required("entry_id"): str,
        vol.Optional("view", default="songs"): vol.In(["songs", "artists"]),
        vol.Optional("query"): str,
        vol.Optional("sort", default="last"): vol.In(["last", "plays", "seconds"]),
        vol.Optional("limit", default=200): vol.All(int, vol.Range(min=1, max=1000)),
    }
)
@require_access
@callback
def ws_history(hass: HomeAssistant, connection, msg) -> None:
    """Music this speaker has played, to block it or pick it for a schedule."""
    if (manager := _manager(hass, connection, msg)) is None:
        return
    log = manager.activity
    if msg["view"] == "artists":
        items = log.artists(msg.get("query"), msg["limit"])
        for item in items:
            item["blocked"] = _is_blocked(manager, {"title": "", "artist": item["artist"]})
    else:
        items = log.history(msg.get("query"), msg["limit"], msg["sort"])
        for item in items:
            item["blocked"] = _is_blocked(manager, item)
    connection.send_result(msg["id"], {"items": items, "total": len(log.library)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/settings/get", vol.Required("entry_id"): str})
@require_access
@callback
def ws_settings_get(hass: HomeAssistant, connection, msg) -> None:
    if (manager := _manager(hass, connection, msg)) is None:
        return
    o = manager.options
    tts = sorted(s.entity_id for s in hass.states.async_all("tts"))
    speakers = sorted(
        ({"entity_id": s.entity_id, "name": s.name} for s in hass.states.async_all("media_player")),
        key=lambda x: x["name"].casefold(),
    )
    connection.send_result(
        msg["id"],
        {
            CONF_DAILY_BUDGET: manager.daily_budget,
            CONF_WARN_MINUTES: manager.warn_minutes,
            CONF_QUIET_WINDOWS: ", ".join(w.format() for w in manager.quiet_windows),
            CONF_ADULT_MODE_DURATION: manager.adult_mode_duration,
            CONF_LIMIT_ACTION: manager.limit_action,
            CONF_FILTER_ACTION: manager.filter_action,
            CONF_MAX_VOLUME: manager.max_volume,
            CONF_ANNOUNCE_TTS: o.get(CONF_ANNOUNCE_TTS),
            CONF_ANNOUNCE_ON_PLAYER: bool(o.get(CONF_ANNOUNCE_ON_PLAYER)),
            CONF_ANNOUNCE_PLAYERS: list(o.get(CONF_ANNOUNCE_PLAYERS) or []),
            "filter": manager.filter_rules(),
            "tts_entities": tts,
            "speakers": speakers,
            "sources": manager.player.source_list,
            "capabilities": manager.player.capabilities(),
            CONF_MA_PLAYER: o.get(CONF_MA_PLAYER),
            "ma_players": _ma_players(hass),
            "ma_link": ma_link_summary(manager),
        },
    )


def _ma_players(hass: HomeAssistant) -> list[dict[str, Any]]:
    from .ma_link import ma_entities

    result = []
    for entry in ma_entities(hass):
        state = hass.states.get(entry.entity_id)
        result.append({"entity_id": entry.entity_id, "name": state.name if state else entry.entity_id})
    return sorted(result, key=lambda x: x["name"].casefold())


def _save_options(manager: MediaManager, changes: dict[str, dict[str, Any]]) -> None:
    entry = manager.entry
    options = {k: (dict(v) if isinstance(v, dict) else v) for k, v in entry.options.items()}
    for section, values in changes.items():
        options.setdefault(section, {}).update(values)
    # The update listener applies them straight away, without a reload.
    manager.hass.config_entries.async_update_entry(entry, options=options)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/settings/set",
        vol.Required("entry_id"): str,
        **{vol.Optional(key): validator for key, (_, validator) in SETTINGS.items()},
    }
)
@require_access
@callback
def ws_settings_set(hass: HomeAssistant, connection, msg) -> None:
    if (manager := _manager(hass, connection, msg)) is None:
        return
    changes: dict[str, dict[str, Any]] = {}
    for key, (section, _) in SETTINGS.items():
        if key not in msg:
            continue
        value = msg[key]
        if key == CONF_QUIET_WINDOWS:
            try:
                value = ", ".join(w.format() for w in parse_windows(value))
            except ValueError as err:
                connection.send_error(msg["id"], "invalid_format", f"Quiet windows: {err}")
                return
        if key == CONF_ANNOUNCE_TTS:
            value = value or None
        if key == CONF_MA_PLAYER:
            value = value or None
            entity = er.async_get(hass).async_get(value) if value else None
            if value and (entity is None or entity.platform != "music_assistant"):
                connection.send_error(msg["id"], "invalid_format", f"{value} isn't a Music Assistant player")
                return
        changes.setdefault(section, {})[key] = value
    announce = {**{k: manager.options.get(k) for k in (CONF_ANNOUNCE_TTS, CONF_ANNOUNCE_ON_PLAYER, CONF_ANNOUNCE_PLAYERS)},
                **changes.get(SECTION_ANNOUNCE, {})}
    if (announce.get(CONF_ANNOUNCE_ON_PLAYER) or announce.get(CONF_ANNOUNCE_PLAYERS)) and not announce.get(CONF_ANNOUNCE_TTS):
        connection.send_error(msg["id"], "invalid_format", "Pick a voice to say warnings with.")
        return
    _save_options(manager, changes)
    connection.send_result(msg["id"], {"saved": changes})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/filter/update",
        vol.Required("entry_id"): str,
        vol.Required("kind"): vol.In(list(BLOCK_KINDS)),
        vol.Required("value"): vol.All(str, vol.Strip, vol.Length(min=1, max=200)),
        vol.Required("add"): bool,
    }
)
@require_access
@callback
def ws_filter_update(hass: HomeAssistant, connection, msg) -> None:
    """Block or unblock one song, artist, album, app or word."""
    if (manager := _manager(hass, connection, msg)) is None:
        return
    changed = manager.update_filter(msg["kind"], msg["value"], add=msg["add"], by=_by(connection))
    connection.send_result(msg["id"], {"changed": changed, "filter": manager.filter_rules()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/filter/set",
        vol.Required("entry_id"): str,
        vol.Required("filter"): {vol.In(list(BLOCK_KINDS)): [str]},
    }
)
@require_access
@callback
def ws_filter_set(hass: HomeAssistant, connection, msg) -> None:
    """Replace whole lists of blocked music."""
    if (manager := _manager(hass, connection, msg)) is None:
        return
    rules = {kind: clean_list(values) for kind, values in msg["filter"].items()}
    manager.save_filter(rules)
    connection.send_result(msg["id"], {"filter": rules})


SCHEDULE_FIELDS = vol.Schema(
    {
        vol.Optional("id"): vol.Any(None, str),
        vol.Required("name"): vol.All(str, vol.Length(max=60)),
        vol.Optional("enabled", default=True): bool,
        vol.Required("days"): [vol.All(int, vol.Range(min=0, max=6))],
        vol.Optional("start"): vol.Any(None, str),
        vol.Optional("stop"): vol.Any(None, str),
        vol.Optional("play_kind", default="artist"): vol.In(PLAY_KINDS),
        vol.Optional("play_value", default=""): str,
        vol.Optional("content_type"): vol.Any(None, str),
        vol.Optional("shuffle", default=True): bool,
        vol.Optional("repeat", default="all"): vol.In(["off", "all", "one"]),
        vol.Optional("volume"): vol.Any(None, vol.All(int, vol.Range(min=0, max=100))),
        vol.Optional("volume_limit"): vol.Any(None, vol.All(int, vol.Range(min=5, max=100))),
        vol.Optional("fade_minutes", default=0): vol.All(int, vol.Range(min=0, max=60)),
        vol.Optional("stop_action", default="pause"): vol.In(["pause", "stop", "turn_off"]),
        vol.Optional("lift_limits", default=True): bool,
    },
    extra=vol.REMOVE_EXTRA,
)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/schedule/save",
        vol.Required("entry_id"): str,
        vol.Required("schedule"): dict,
    }
)
@require_access
@callback
def ws_schedule_save(hass: HomeAssistant, connection, msg) -> None:
    if (manager := _manager(hass, connection, msg)) is None:
        return
    try:
        sched = manager.save_schedule(SCHEDULE_FIELDS(msg["schedule"]), by=_by(connection))
    except (vol.Invalid, ValueError) as err:
        connection.send_error(msg["id"], "invalid_format", str(err).capitalize())
        return
    connection.send_result(msg["id"], {"schedule": sched.as_dict(), "schedules": schedule_summary(manager)})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/schedule/delete", vol.Required("entry_id"): str, vol.Required("schedule_id"): str}
)
@require_access
@callback
def ws_schedule_delete(hass: HomeAssistant, connection, msg) -> None:
    if (manager := _manager(hass, connection, msg)) is None:
        return
    manager.delete_schedule(msg["schedule_id"])
    connection.send_result(msg["id"], {"schedules": schedule_summary(manager)})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/schedule/run", vol.Required("entry_id"): str, vol.Required("schedule_id"): str}
)
@require_access
@websocket_api.async_response
async def ws_schedule_run(hass: HomeAssistant, connection, msg) -> None:
    """Start a schedule's music now, to try it out."""
    if (manager := _manager(hass, connection, msg)) is None:
        return
    if (sched := manager.schedule_by_id(msg["schedule_id"])) is None:
        connection.send_error(msg["id"], "not_found", "Schedule not found")
        return
    if sched.limit_only:
        connection.send_error(msg["id"], "not_supported", f"{sched.name} only limits the volume, so there's nothing to play")
        return
    ok = await manager.async_start_schedule(sched, by=_by(connection), manual=True)
    last = next((e for e in reversed(manager.activity.events) if e["type"] == "schedule"), {})
    connection.send_result(msg["id"], {"ok": ok, "detail": last.get("detail")})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/action",
        vol.Required("entry_id"): str,
        vol.Required("action"): vol.In(ACTIONS),
        vol.Optional("minutes"): vol.All(int, vol.Range(min=-240, max=720)),
        vol.Optional("fade_minutes"): vol.All(int, vol.Range(min=0, max=60)),
        vol.Optional("mode"): vol.In(MODES),
        vol.Optional("enabled"): bool,
    }
)
@require_access
@callback
def ws_action(hass: HomeAssistant, connection, msg) -> None:
    if (manager := _manager(hass, connection, msg)) is None:
        return
    action = msg["action"]
    try:
        if action == "grant_extension":
            manager.grant_extension(msg["minutes"])
        elif action == "force_block":
            manager.force_block()
        elif action == "unblock":
            manager.unblock()
        elif action == "reset_usage":
            manager.reset_usage()
        elif action == "set_mode":
            manager.set_mode(msg["mode"])
        elif action == "set_adult_mode":
            manager.set_adult_mode(msg["enabled"], msg.get("minutes"))
        elif action == "set_music_filter":
            manager.set_music_filter(msg["enabled"])
        elif action == "set_sleep_timer":
            if msg["minutes"] < 1:
                raise KeyError("minutes")
            manager.set_sleep_timer(msg["minutes"], msg.get("fade_minutes", 0), by=_by(connection))
        elif action == "cancel_sleep_timer":
            manager.cancel_sleep_timer(by=_by(connection))
    except KeyError as err:
        connection.send_error(msg["id"], "invalid_format", f"{action} needs {err.args[0]}")
        return
    connection.send_result(msg["id"], {"profile": profile_summary(manager)})


# ---- access ---------------------------------------------------------------------


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/access/me"})
@callback
def ws_access_me(hass: HomeAssistant, connection, msg) -> None:
    user = connection.user
    connection.send_result(
        msg["id"],
        {
            "allowed": get_access(hass).allows(user),
            "is_admin": bool(user and user.is_admin),
            "user_id": user.id if user else None,
            "name": user.name if user else None,
        },
    )


async def _people(hass: HomeAssistant) -> list[dict[str, Any]]:
    users = [u for u in await hass.auth.async_get_users() if not u.system_generated and u.is_active]
    return [
        {"id": u.id, "name": u.name or u.id, "is_admin": u.is_admin, "is_owner": u.is_owner}
        for u in sorted(users, key=lambda u: (u.name or "").casefold())
    ]


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/access/get"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_access_get(hass: HomeAssistant, connection, msg) -> None:
    connection.send_result(msg["id"], {"user_ids": list(get_access(hass).user_ids), "people": await _people(hass)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/access/set", vol.Required("user_ids"): [str]})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_access_set(hass: HomeAssistant, connection, msg) -> None:
    from .panel import async_register_panel

    access = get_access(hass)
    await access.async_set(msg["user_ids"])
    await async_register_panel(hass, update=True)
    connection.send_result(msg["id"], {"user_ids": list(access.user_ids), "people": await _people(hass)})


# ---- speakers (admin only, like Home Assistant's own integration settings) ----------


def _managed_players(hass: HomeAssistant) -> set[str]:
    return {e.data.get("media_player") for e in hass.config_entries.async_entries(DOMAIN)}


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/speakers/candidates"})
@websocket_api.require_admin
@callback
def ws_speakers_candidates(hass: HomeAssistant, connection, msg) -> None:
    """Media players Media Mgmt doesn't manage yet, to add from the sidebar app."""
    managed = _managed_players(hass)
    registry = er.async_get(hass)
    players = []
    for state in hass.states.async_all("media_player"):
        if state.entity_id in managed:
            continue
        entity = registry.async_get(state.entity_id)
        if entity and (entity.disabled or entity.hidden):
            continue
        players.append(
            {
                "entity_id": state.entity_id,
                "name": state.name,
                "state": state.state,
                "platform": entity.platform if entity else None,
            }
        )
    players.sort(key=lambda p: (p["name"] or "").casefold())
    connection.send_result(msg["id"], {"players": players})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/speakers/add", vol.Required("entity_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_speakers_add(hass: HomeAssistant, connection, msg) -> None:
    """Add a speaker with the default rules, through the same steps as Settings."""
    from homeassistant.config_entries import SOURCE_USER
    from homeassistant.data_entry_flow import FlowResultType

    entity_id = msg["entity_id"]
    if not entity_id.startswith("media_player.") or hass.states.get(entity_id) is None:
        connection.send_error(msg["id"], "not_found", f"No media player {entity_id}")
        return
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await flow.async_configure(result["flow_id"], {"media_player": entity_id})
    if result["type"] is FlowResultType.ABORT:
        connection.send_error(msg["id"], "already_configured", "Media Mgmt already manages this speaker")
        return
    # The settings step with every section left at its defaults.
    sections = {SECTION_LISTENING: {}, SECTION_FILTER: {}, SECTION_VOLUME: {}, SECTION_ANNOUNCE: {}, SECTION_PLAYBACK: {}}
    try:
        result = await flow.async_configure(result["flow_id"], sections)
    except vol.Invalid as err:
        flow.async_abort(result["flow_id"])
        connection.send_error(msg["id"], "add_failed", f"Couldn't add the speaker: {err}")
        return
    if result["type"] is not FlowResultType.CREATE_ENTRY:
        flow.async_abort(result["flow_id"])
        connection.send_error(msg["id"], "add_failed", "Couldn't add the speaker")
        return
    entry = result["result"]
    connection.send_result(msg["id"], {"entry_id": entry.entry_id, "name": entry.title})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/speakers/remove", vol.Required("entry_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_speakers_remove(hass: HomeAssistant, connection, msg) -> None:
    """Stop managing a speaker. Its history, rules and schedules are deleted."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Media Mgmt profile not found")
        return
    await hass.config_entries.async_remove(entry.entry_id)
    connection.send_result(msg["id"], {"removed": entry.entry_id})


# ---- live updates -------------------------------------------------------------------


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@require_access
@callback
def ws_subscribe(hass: HomeAssistant, connection, msg) -> None:
    """Send an event whenever any profile changes, carrying its entry_id."""

    @callback
    def forward(entry_id: str) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"entry_id": entry_id}))

    @callback
    def artists_changed() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"entry_id": None, "artists": True}))

    unsubs = [
        async_dispatcher_connect(hass, SIGNAL_ANY_UPDATED, forward),
        async_dispatcher_connect(hass, SIGNAL_ARTISTS_UPDATED, artists_changed),
    ]

    @callback
    def unsubscribe() -> None:
        for unsub in unsubs:
            unsub()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])


# ---- saved artists ------------------------------------------------------------------


def _speaker_choices(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [
        {
            "entry_id": m.entry.entry_id,
            "name": m.name,
            "entity_id": m.entity_id,
            "music_assistant": m.player.ma_entity_id is not None,
        }
        for m in _managers(hass)
    ]


def _search_config_entry(hass: HomeAssistant, manager: MediaManager | None = None) -> str | None:
    """The Music Assistant config entry to search with, or None if search isn't possible."""
    from .ma_link import ma_config_entry

    if not hass.services.has_service("music_assistant", "search"):
        return None
    if manager is not None and (cid := ma_config_entry(hass, manager.ma_link)):
        return cid
    return next((cid for m in _managers(hass) if (cid := m.ma_link.config_entry_id)), None) or ma_config_entry(hass)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/artists/list"})
@require_access
@callback
def ws_artists_list(hass: HomeAssistant, connection, msg) -> None:
    """The home's saved artists, the speakers they can play on, and whether search works."""
    from .saved import get_saved

    connection.send_result(
        msg["id"],
        {
            "artists": [a.as_dict() for a in get_saved(hass).artists],
            "speakers": _speaker_choices(hass),
            "search": _search_config_entry(hass) is not None,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/artists/search",
        vol.Required("query"): vol.All(str, vol.Strip, vol.Length(min=1, max=200)),
        vol.Optional("media_type", default="artist"): vol.In(["artist", "album", "track", "playlist"]),
        vol.Optional("entry_id"): str,
        vol.Optional("limit", default=12): vol.All(int, vol.Range(min=1, max=50)),
    }
)
@require_access
@websocket_api.async_response
async def ws_artists_search(hass: HomeAssistant, connection, msg) -> None:
    """Search Music Assistant (every music provider it has) for an artist."""
    from .playback import ma_search, result_item

    manager = None
    if msg.get("entry_id") and (manager := _manager(hass, connection, msg)) is None:
        return
    results = await ma_search(
        hass, _search_config_entry(hass, manager), msg["query"], msg["media_type"], limit=msg["limit"]
    )
    if results is None:
        connection.send_error(
            msg["id"], "not_supported",
            "Searching needs Music Assistant. Add the Music Assistant integration, then try again.",
        )
        return
    connection.send_result(msg["id"], {"items": [result_item(r) for r in results]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/artists/save",
        vol.Required("artist"): {
            vol.Optional("id"): vol.Any(None, str),
            vol.Required("name"): vol.All(str, vol.Strip, vol.Length(min=1, max=120)),
            vol.Optional("uri"): vol.Any(None, vol.All(str, vol.Strip, vol.Length(max=1000))),
            vol.Optional("provider"): vol.Any(None, str),
            vol.Optional("image"): vol.Any(None, vol.All(str, vol.Length(max=2000))),
            vol.Optional("aliases"): vol.Any(None, str, [str]),
            vol.Optional("speaker"): vol.Any(None, str),
            vol.Optional("radio"): bool,
            vol.Optional("shuffle"): bool,
            vol.Optional("volume"): vol.Any(None, vol.All(int, vol.Range(min=0, max=100))),
            # Sent back as it came from artists/list; the stored date is kept.
            vol.Optional("added"): vol.Any(None, str, int, float),
        },
        # Saved from what played before: look the artist up in Music Assistant.
        vol.Optional("find", default=False): bool,
    }
)
@require_access
@websocket_api.async_response
async def ws_artists_save(hass: HomeAssistant, connection, msg) -> None:
    """Save an artist for the whole home (or change one)."""
    from .artists import best_match, provider_of
    from .playback import ma_search
    from .saved import get_saved

    data = dict(msg["artist"])
    if msg["find"] and not data.get("uri"):
        results = await ma_search(hass, _search_config_entry(hass), data["name"], "artist", limit=5)
        if results and (best := best_match(results, data["name"])):
            data["uri"] = best["uri"]
            data["provider"] = provider_of(best["uri"])
            data["image"] = data.get("image") or best.get("image")
    try:
        artist = get_saved(hass).save(data)
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"artist": artist.as_dict()})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/artists/delete", vol.Required("artist_id"): str}
)
@require_access
@callback
def ws_artists_delete(hass: HomeAssistant, connection, msg) -> None:
    from .saved import get_saved

    if not get_saved(hass).delete(msg["artist_id"]):
        connection.send_error(msg["id"], "not_found", "Saved artist not found")
        return
    connection.send_result(msg["id"], {"deleted": msg["artist_id"]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/artists/play",
        vol.Required("artist"): vol.All(str, vol.Strip, vol.Length(min=1, max=500)),
        vol.Optional("entry_id"): vol.Any(None, str),
        vol.Optional("uri"): vol.Any(None, str),
        vol.Optional("media_type", default="artist"): vol.In(["artist", "album", "track", "playlist"]),
        vol.Optional("radio"): bool,
        vol.Optional("shuffle"): bool,
        vol.Optional("volume"): vol.Any(None, vol.All(int, vol.Range(min=0, max=100))),
    }
)
@require_access
@websocket_api.async_response
async def ws_artists_play(hass: HomeAssistant, connection, msg) -> None:
    """Play a saved artist, or a search result, on a speaker. The rules still apply."""
    from .saved import async_play_request

    result = await async_play_request(
        hass,
        msg["artist"],
        profile_id=msg.get("entry_id"),
        media_type=msg["media_type"],
        uri=msg.get("uri"),
        radio=msg.get("radio"),
        shuffle=msg.get("shuffle"),
        volume=msg.get("volume"),
        by=_by(connection),
    )
    connection.send_result(msg["id"], result.as_dict())
