from datetime import timedelta

from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.ha.test_integration import P, SPEAKER, set_speaker, setup

DOMAIN = "media_mgmt"
FRIDAY_EVENING = "2026-10-16 19:44:00-07:00"  # the test harness runs in US/Pacific


async def tick(hass, freezer, seconds=30):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_bedtime_schedule_plays_through_quiet_window_then_fades_and_stops(hass: HomeAssistant, freezer, calls) -> None:
    freezer.move_to(FRIDAY_EVENING)
    set_speaker(hass, state="idle", title=None, volume=0.6)
    entry = await setup(hass, listening={"quiet_windows": "19:00-07:00 Bedtime"})
    manager = entry.runtime_data
    sched = manager.save_schedule({
        "name": "Bedtime music", "days": [0, 1, 2, 3, 4, 5, 6], "start": "19:45", "stop": "19:50",
        "play_kind": "source", "play_value": "Bedtime favourites", "volume": 25, "fade_minutes": 2,
    })
    assert manager.decision.state == "enforcing"  # bedtime quiet window

    for _ in range(2):
        await tick(hass, freezer)
    assert calls["select_source"][-1].data["source"] == "Bedtime favourites"
    assert calls["volume_set"][-1].data["volume_level"] == 0.25
    assert hass.states.get(f"sensor.media_mgmt_{P}_enforcement_state").state == "schedule"

    # The speaker starts playing: the quiet window doesn't stop it.
    set_speaker(hass, title="Lullaby", artist="Brahms", volume=0.25)
    await tick(hass, freezer, 5)
    assert calls["media_pause"] == []

    # 19:48: fading
    for _ in range(6):
        await tick(hass, freezer)
    assert calls["volume_set"][-1].data["volume_level"] < 0.25
    # 19:50: stopped, volume put back for tomorrow
    for _ in range(5):
        await tick(hass, freezer)
    assert len(calls["media_pause"]) >= 1
    assert calls["volume_set"][-1].data["volume_level"] == 0.25
    assert manager.state.schedule_runs[sched.id]["stopped"] == "2026-10-16"
    set_speaker(hass, state="paused", title="Lullaby", artist="Brahms", volume=0.25)
    await tick(hass, freezer)
    assert manager.decision.state == "enforcing"
    # Schedule time doesn't count toward the daily limit (only the moments
    # after it ended, before the speaker reported it paused).
    assert manager.state.schedule_seconds == 300
    assert manager.state.used_seconds <= 60


async def test_artist_from_history_without_music_assistant(hass: HomeAssistant, freezer, calls) -> None:
    freezer.move_to(FRIDAY_EVENING)
    set_speaker(hass, title="Lullaby", artist="Brahms", media_content_id="spotify:track:abc", media_content_type="music")
    entry = await setup(hass)
    manager = entry.runtime_data
    set_speaker(hass, state="idle", title=None)
    await hass.async_block_till_done()
    sched = manager.save_schedule({"name": "Bedtime", "days": [4], "start": "19:45", "play_kind": "artist", "play_value": "brahms"})
    for _ in range(2):
        await tick(hass, freezer)
    assert calls["play_media"][-1].data["media_content_id"] == "spotify:track:abc"
    assert calls["shuffle_set"] and calls["repeat_set"]
    # Started once only
    await tick(hass, freezer)
    assert len(calls["play_media"]) == 1
    assert manager.state.schedule_runs[sched.id]["started"] == "2026-10-16"


async def test_artist_with_music_assistant(hass: HomeAssistant, freezer, calls, entity_registry: er.EntityRegistry) -> None:
    freezer.move_to(FRIDAY_EVENING)
    entity_registry.async_get_or_create("media_player", "music_assistant", "kids", suggested_object_id="kids_room")
    ma = async_mock_service(hass, "music_assistant", "play_media")
    set_speaker(hass, state="idle", title=None)
    entry = await setup(hass)
    entry.runtime_data.save_schedule({"name": "Bedtime", "days": [4], "start": "20:00", "play_kind": "artist", "play_value": "Brahms"})
    await hass.services.async_call(DOMAIN, "run_schedule", {"profile_id": entry.entry_id, "schedule": "bedtime"}, blocking=True)
    assert ma[-1].data == {"entity_id": SPEAKER, "media_id": "Brahms", "media_type": "artist", "enqueue": "replace"}


async def test_unknown_artist_fails_cleanly(hass: HomeAssistant, freezer, calls) -> None:
    freezer.move_to(FRIDAY_EVENING)
    set_speaker(hass, state="idle", title=None)
    entry = await setup(hass)
    events = []
    hass.bus.async_listen("media_mgmt_schedule", events.append)
    sched = entry.runtime_data.save_schedule({"name": "Bedtime", "days": [4], "start": "20:00", "play_kind": "artist", "play_value": "Nobody"})
    ok = await entry.runtime_data.async_start_schedule(sched)
    await hass.async_block_till_done()
    assert ok is False
    assert events[-1].data["action"] == "failed"
    assert calls["play_media"] == []


async def test_stop_only_schedule_is_a_nightly_sleep_timer(hass: HomeAssistant, freezer, calls) -> None:
    freezer.move_to("2026-10-16 20:29:00-07:00")
    set_speaker(hass)
    entry = await setup(hass)
    entry.runtime_data.save_schedule({"name": "Lights out", "days": [4], "stop": "20:30", "stop_action": "stop"})
    for _ in range(3):
        await tick(hass, freezer)
    assert len(calls["media_stop"]) == 1


async def test_schedule_repeats_every_night(hass: HomeAssistant, freezer, calls) -> None:
    """Bedtime music starts and stops again the next night, on its own."""
    freezer.move_to(FRIDAY_EVENING)  # 19:44
    set_speaker(hass, state="idle", title=None, volume=0.5)
    entry = await setup(hass)
    manager = entry.runtime_data
    sched = manager.save_schedule({
        "name": "Bedtime music", "days": [0, 1, 2, 3, 4, 5, 6], "start": "19:45", "stop": "20:15",
        "play_kind": "source", "play_value": "Bedtime favourites", "volume": 20,
    })
    for night, day in ((1, "2026-10-16"), (2, "2026-10-17")):
        if night == 2:
            freezer.move_to("2026-10-17 19:44:00-07:00")
            set_speaker(hass, state="idle", title=None, volume=0.5)
            await tick(hass, freezer)
        for _ in range(2):
            await tick(hass, freezer)
        assert len(calls["select_source"]) == night, f"night {night} didn't start"
        set_speaker(hass, title="Lullaby", artist="Brahms", volume=0.2)
        await tick(hass, freezer, 5)
        freezer.move_to(f"{day} 20:15:05-07:00")
        await tick(hass, freezer, 1)
        assert len(calls["media_pause"]) == night, f"night {night} didn't stop"
        assert manager.state.schedule_runs[sched.id] == {"started": day, "stopped": day}
        set_speaker(hass, state="paused", title="Lullaby", artist="Brahms", volume=0.5)
        await tick(hass, freezer)
