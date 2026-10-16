from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from homeassistant.core import HomeAssistant

DOMAIN = "media_mgmt"
SPEAKER = "media_player.kids_room"
P = "kids_room"
ALL_FEATURES = 1 | 4 | 16 | 32 | 128 | 256 | 512 | 2048 | 4096 | 16384 | 32768 | 262144 | 1048576


def set_speaker(hass, state="playing", title="Clair de Lune", artist="Debussy", album="Suite", volume=0.3, **extra):
    attrs = {
        "friendly_name": "Kids Room",
        "supported_features": ALL_FEATURES,
        "volume_level": volume,
        "source_list": ["Bedtime favourites", "Radio"],
    }
    if title:
        attrs.update({"media_title": title, "media_artist": artist, "media_album_name": album, "app_name": "Spotify"})
    attrs.update(extra)
    hass.states.async_set(SPEAKER, state, attrs)


def options(**over):
    base = {
        "listening": {"daily_budget": 0, "warn_minutes": 5, "quiet_windows": "", "limit_action": "pause", "adult_mode_duration": 120},
        "filter": {"blocked_tracks": [], "blocked_artists": [], "blocked_albums": [], "blocked_sources": [], "blocked_keywords": [], "filter_action": "skip"},
        "volume": {"max_volume": 100},
        "announcements": {"announce_tts": None, "announce_on_player": False, "announce_players": []},
    }
    for section, values in over.items():
        base[section].update(values)
    return base


async def setup(hass, **over):
    entry = MockConfigEntry(domain=DOMAIN, title="Kids Room", unique_id=SPEAKER, data={"media_player": SPEAKER}, options=options(**over))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def advance(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_entities_created(hass: HomeAssistant, calls) -> None:
    set_speaker(hass)
    await setup(hass)
    for entity_id in (
        f"select.media_mgmt_{P}_mode",
        f"switch.media_mgmt_{P}_music_filter",
        f"switch.media_mgmt_{P}_adult_mode",
        f"sensor.media_mgmt_{P}_enforcement_state",
        f"sensor.media_mgmt_{P}_listening_time_today",
        f"sensor.media_mgmt_{P}_now_playing",
        f"sensor.media_mgmt_{P}_songs_today",
        f"sensor.media_mgmt_{P}_sleep_timer",
        f"button.media_mgmt_{P}_block_this_song",
        f"button.media_mgmt_{P}_block_this_artist",
    ):
        assert hass.states.get(entity_id) is not None, entity_id
    assert hass.states.get(f"sensor.media_mgmt_{P}_now_playing").state == "Clair de Lune by Debussy"
    assert hass.states.get(f"sensor.media_mgmt_{P}_songs_today").state == "1"
    assert hass.states.get(f"sensor.media_mgmt_{P}_enforcement_state").state == "ok"


async def test_limit_pauses_music(hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls) -> None:
    set_speaker(hass)
    await setup(hass, listening={"daily_budget": 1})
    for _ in range(5):
        await advance(hass, freezer, 30)
    assert hass.states.get(f"sensor.media_mgmt_{P}_enforcement_state").state == "enforcing"
    await advance(hass, freezer, 5)
    assert len(calls["media_pause"]) >= 1


async def test_blocked_artist_skipped(hass: HomeAssistant, freezer, calls) -> None:
    set_speaker(hass)
    await setup(hass, filter={"blocked_artists": ["Baby Shark Band"]})
    events = []
    hass.bus.async_listen("media_mgmt_media_blocked", events.append)
    set_speaker(hass, title="Baby Shark", artist="Baby Shark Band & Friends")
    await hass.async_block_till_done()
    await advance(hass, freezer, 3)
    assert len(calls["media_next_track"]) == 1
    assert events[0].data["rule_kind"] == "artist"
    assert hass.states.get(f"sensor.media_mgmt_{P}_blocked_today").state == "1"


async def test_block_current_button_applies_live(hass: HomeAssistant, freezer, calls) -> None:
    set_speaker(hass)
    entry = await setup(hass)
    await hass.services.async_call("button", "press", {"entity_id": f"button.media_mgmt_{P}_block_this_artist"}, blocking=True)
    await hass.async_block_till_done()
    assert entry.options["filter"]["blocked_artists"] == ["Debussy"]
    await advance(hass, freezer, 3)
    assert len(calls["media_next_track"]) == 1
    # Applied without reloading: the same manager is still running.
    assert entry.runtime_data.filter.artists == ["Debussy"]


async def test_volume_cap(hass: HomeAssistant, calls) -> None:
    set_speaker(hass, volume=0.3)
    await setup(hass, volume={"max_volume": 40})
    set_speaker(hass, volume=0.9)
    await hass.async_block_till_done()
    assert calls["volume_set"][-1].data["volume_level"] == 0.4


async def test_sleep_timer_fades_and_pauses(hass: HomeAssistant, freezer, calls) -> None:
    set_speaker(hass, volume=0.5)
    entry = await setup(hass)
    await hass.services.async_call(DOMAIN, "set_sleep_timer", {"profile_id": entry.entry_id, "minutes": 2, "fade_minutes": 1}, blocking=True)
    assert hass.states.get(f"sensor.media_mgmt_{P}_sleep_timer").state not in ("unknown", None)
    await advance(hass, freezer, 75)
    assert calls["volume_set"], "fade should turn the volume down"
    assert calls["volume_set"][-1].data["volume_level"] < 0.5
    await advance(hass, freezer, 60)
    assert len(calls["media_pause"]) == 1
    # Volume put back for next time.
    assert calls["volume_set"][-1].data["volume_level"] == 0.5
    assert hass.states.get(f"sensor.media_mgmt_{P}_sleep_timer").state == "unknown"
