"""Media Mgmt: listening limits, blocked music, schedules and analytics for speakers."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_MINUTES,
    ATTR_PROFILE_ID,
    BLOCK_KINDS,
    DOMAIN,
    SERVICE_BLOCK_MEDIA,
    SERVICE_CANCEL_SLEEP_TIMER,
    SERVICE_FORCE_BLOCK,
    SERVICE_GRANT_EXTENSION,
    SERVICE_PLAY_ARTIST,
    SERVICE_RESET_USAGE,
    SERVICE_RUN_SCHEDULE,
    SERVICE_SET_SLEEP_TIMER,
    SERVICE_UNBLOCK,
    SERVICE_UNBLOCK_MEDIA,
)
from .manager import MediaManager

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type MediaMgmtConfigEntry = ConfigEntry[MediaManager]

PROFILE_SCHEMA = vol.Schema({vol.Required(ATTR_PROFILE_ID): cv.string})
EXTENSION_SCHEMA = PROFILE_SCHEMA.extend(
    {vol.Required(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=-240, max=240))}
)
BLOCK_SCHEMA = vol.All(
    PROFILE_SCHEMA.extend(
        {
            vol.Required("kind"): vol.In(list(BLOCK_KINDS)),
            vol.Optional("value"): vol.All(
                cv.string, vol.Strip, vol.Length(min=1, max=200)
            ),
            vol.Optional("current", default=False): cv.boolean,
        }
    ),
    cv.has_at_least_one_key("value", "current"),
)
UNBLOCK_SCHEMA = PROFILE_SCHEMA.extend(
    {
        vol.Required("kind"): vol.In(list(BLOCK_KINDS)),
        vol.Required("value"): vol.All(
            cv.string, vol.Strip, vol.Length(min=1, max=200)
        ),
    }
)
SLEEP_SCHEMA = PROFILE_SCHEMA.extend(
    {
        vol.Required(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=720)),
        vol.Optional("fade_minutes", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=60)
        ),
    }
)
SCHEDULE_SCHEMA = PROFILE_SCHEMA.extend({vol.Required("schedule"): cv.string})
PLAY_ARTIST_SCHEMA = vol.Schema(
    {
        vol.Required("artist"): vol.All(
            cv.string, vol.Strip, vol.Length(min=1, max=500)
        ),
        vol.Optional(ATTR_PROFILE_ID): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("speaker"): vol.Any(
            None, vol.All(cv.string, vol.Strip, vol.Length(max=100))
        ),
        vol.Optional("area_id"): vol.Any(None, cv.string),
        vol.Optional("media_type", default="artist"): vol.In(
            ["artist", "album", "track", "playlist"]
        ),
        vol.Optional("uri"): vol.Any(
            None, vol.All(cv.string, vol.Strip, vol.Length(max=1000))
        ),
        vol.Optional("radio_mode"): cv.boolean,
        vol.Optional("shuffle"): cv.boolean,
        vol.Optional("volume"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("enqueue", default="replace"): vol.In(
            ["play", "replace", "next", "add"]
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    from . import websocket
    from .access import async_get_access
    from .intent import async_setup_intents
    from .panel import async_register_panel
    from .saved import async_load_saved

    await async_get_access(hass)
    await async_load_saved(hass)
    _register_services(hass)
    websocket.async_register(hass)
    await async_setup_intents(hass)
    await async_register_panel(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MediaMgmtConfigEntry) -> bool:
    manager = MediaManager(hass, entry)
    await manager.async_start()
    entry.runtime_data = manager
    _link_devices(hass, entry, manager)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MediaMgmtConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: MediaMgmtConfigEntry) -> None:
    from .storage import ActivityStore, ProfileStore, ScheduleStore

    for store in (ProfileStore, ActivityStore, ScheduleStore):
        await store(hass, entry.entry_id).async_remove()


async def _async_update_listener(
    hass: HomeAssistant, entry: MediaMgmtConfigEntry
) -> None:
    """Settings changed: use them straight away, without reloading the profile."""
    if entry.state is ConfigEntryState.LOADED:
        entry.runtime_data.apply_options(dict(entry.options))


# ---- linked devices ----------------------------------------------------------------


def _link_devices(
    hass: HomeAssistant, entry: ConfigEntry, manager: MediaManager
) -> None:
    """Show Media Mgmt with the speaker's own device."""
    registry = dr.async_get(hass)
    entity = er.async_get(hass).async_get(manager.entity_id)
    speaker = (
        registry.async_get(entity.device_id) if entity and entity.device_id else None
    )
    # Devices from different integrations that share an identifier are listed
    # under each other's Linked devices.
    own_id = (DOMAIN, entry.entry_id)
    own = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={own_id},
        name=f"Media Mgmt — {entry.title}",
        manufacturer="Media Mgmt",
        model="Speaker profile",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    shared = (
        set(speaker.identifiers)
        if speaker and speaker.config_entry_id != entry.entry_id
        else set()
    )
    changes: dict = {"new_identifiers": {own_id, *shared}}
    if own.via_device_id is not None:
        # Before 2026.8 the profile was shown under the speaker instead.
        changes["via_device_id"] = None
    registry.async_update_device(own.id, **changes)


# ---- services -----------------------------------------------------------------------


def _manager(hass: HomeAssistant, call: ServiceCall) -> MediaManager:
    entry_id = call.data[ATTR_PROFILE_ID]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="profile_not_found",
            translation_placeholders={"profile_id": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="profile_not_loaded",
            translation_placeholders={"profile": entry.title},
        )
    return entry.runtime_data


async def _user_name(hass: HomeAssistant, call: ServiceCall) -> str | None:
    if call.context.user_id and (
        user := await hass.auth.async_get_user(call.context.user_id)
    ):
        return user.name
    return None


def current_value(manager: MediaManager, kind: str) -> str:
    """The value to block for what's playing now, e.g. its artist."""
    from .filters import track_entry

    media = manager.player.media
    if not media:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="nothing_playing"
        )
    value = {
        "track": track_entry(media["title"], media.get("artist")),
        "artist": media.get("artist"),
        "album": media.get("album"),
        "source": media.get("source"),
        "keyword": None,
    }.get(kind)
    if not value:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="nothing_to_block",
            translation_placeholders={"kind": kind},
        )
    return value


@callback
def _register_services(hass: HomeAssistant) -> None:
    from .access import async_ensure_allowed

    def simple(method: str):
        async def handler(call: ServiceCall) -> None:
            await async_ensure_allowed(hass, call.context)
            getattr(_manager(hass, call), method)()

        return handler

    async def grant_extension(call: ServiceCall) -> None:
        await async_ensure_allowed(hass, call.context)
        _manager(hass, call).grant_extension(call.data[ATTR_MINUTES])

    async def block_media(call: ServiceCall) -> None:
        await async_ensure_allowed(hass, call.context)
        manager = _manager(hass, call)
        value = call.data.get("value") or current_value(manager, call.data["kind"])
        manager.update_filter(
            call.data["kind"], value, add=True, by=await _user_name(hass, call)
        )

    async def unblock_media(call: ServiceCall) -> None:
        await async_ensure_allowed(hass, call.context)
        _manager(hass, call).update_filter(
            call.data["kind"],
            call.data["value"],
            add=False,
            by=await _user_name(hass, call),
        )

    async def set_sleep_timer(call: ServiceCall) -> None:
        await async_ensure_allowed(hass, call.context)
        _manager(hass, call).set_sleep_timer(
            call.data[ATTR_MINUTES],
            call.data["fade_minutes"],
            by=await _user_name(hass, call),
        )

    async def cancel_sleep_timer(call: ServiceCall) -> None:
        await async_ensure_allowed(hass, call.context)
        _manager(hass, call).cancel_sleep_timer(by=await _user_name(hass, call))

    async def run_schedule(call: ServiceCall) -> None:
        await async_ensure_allowed(hass, call.context)
        manager = _manager(hass, call)
        wanted = call.data["schedule"]
        sched = manager.schedule_by_id(wanted) or next(
            (s for s in manager.schedules if s.name.casefold() == wanted.casefold()),
            None,
        )
        if sched is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="schedule_not_found",
                translation_placeholders={"schedule": wanted},
            )
        if sched.limit_only:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="schedule_limit_only",
                translation_placeholders={"schedule": sched.name},
            )
        await manager.async_start_schedule(
            sched, by=await _user_name(hass, call), manual=True
        )

    async def play_artist(call: ServiceCall) -> ServiceResponse:
        # Playing doesn't change or lift any rule (blocked music, limits, quiet
        # windows and the volume cap all apply), so it's open to everyone,
        # like pressing play on the speaker.
        from .saved import async_play_request

        data = call.data
        result = await async_play_request(
            hass,
            data["artist"],
            profile_id=data.get(ATTR_PROFILE_ID),
            entity_id=data.get("entity_id"),
            speaker=data.get("speaker"),
            area_id=data.get("area_id"),
            media_type=data["media_type"],
            uri=data.get("uri"),
            radio=data.get("radio_mode"),
            shuffle=data.get("shuffle"),
            volume=data.get("volume"),
            enqueue=data["enqueue"],
            by=await _user_name(hass, call),
        )
        if call.return_response:
            return result.as_dict()
        if not result.ok:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="play_failed",
                translation_placeholders={"message": result.message},
            )
        return None

    register = hass.services.async_register
    register(DOMAIN, SERVICE_GRANT_EXTENSION, grant_extension, EXTENSION_SCHEMA)
    register(DOMAIN, SERVICE_FORCE_BLOCK, simple("force_block"), PROFILE_SCHEMA)
    register(DOMAIN, SERVICE_UNBLOCK, simple("unblock"), PROFILE_SCHEMA)
    register(DOMAIN, SERVICE_RESET_USAGE, simple("reset_usage"), PROFILE_SCHEMA)
    register(DOMAIN, SERVICE_BLOCK_MEDIA, block_media, BLOCK_SCHEMA)
    register(DOMAIN, SERVICE_UNBLOCK_MEDIA, unblock_media, UNBLOCK_SCHEMA)
    register(DOMAIN, SERVICE_SET_SLEEP_TIMER, set_sleep_timer, SLEEP_SCHEMA)
    register(DOMAIN, SERVICE_CANCEL_SLEEP_TIMER, cancel_sleep_timer, PROFILE_SCHEMA)
    register(DOMAIN, SERVICE_RUN_SCHEDULE, run_schedule, SCHEDULE_SCHEMA)
    register(
        DOMAIN,
        SERVICE_PLAY_ARTIST,
        play_artist,
        PLAY_ARTIST_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
