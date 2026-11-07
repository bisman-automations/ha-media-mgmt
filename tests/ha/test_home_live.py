"""Whole-home limits, the weekly summary, bedtime fade, Live Activity and extra-time reasons."""

from datetime import datetime

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.media_mgmt.home import HomeSettings
from custom_components.media_mgmt.home_limits import get_home
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from tests.ha.test_integration import (
    ALL_FEATURES,
    DOMAIN,
    SPEAKER,
    P,
    advance,
    options,
    set_speaker,
    setup,
)

OTHER = "media_player.den"


def local(*args) -> datetime:
    return datetime(*args, tzinfo=dt_util.get_default_time_zone())


async def add_other_speaker(hass):
    hass.states.async_set(
        OTHER,
        "playing",
        {
            "friendly_name": "Den",
            "supported_features": ALL_FEATURES,
            "volume_level": 0.3,
            "media_title": "Song",
            "media_artist": "Band",
        },
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Den",
        unique_id=OTHER,
        data={"media_player": OTHER},
        options=options(),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_extra_time_reason_is_in_the_activity(hass: HomeAssistant, calls) -> None:
    set_speaker(hass)
    entry = await setup(hass, listening={"daily_budget": 30})
    await hass.services.async_call(
        DOMAIN,
        "grant_extension",
        {
            "profile_id": entry.entry_id,
            "minutes": 15,
            "reason": "Alex's reward: music time",
            "whole_home": True,
        },
        blocking=True,
    )
    events = entry.runtime_data.activity.events
    extension = next(e for e in events if e["type"] == "extension")
    assert extension["minutes"] == 15
    assert extension["reason"] == "Alex's reward: music time"
    home = next(e for e in events if e["type"] == "home_extension")
    assert home["reason"] == "Alex's reward: music time"
    assert entry.runtime_data.state.extension_minutes == 15


async def test_whole_home_limit_stops_every_speaker(
    hass: HomeAssistant, hass_ws_client, freezer: FrozenDateTimeFactory, calls
) -> None:
    set_speaker(hass)
    first = await setup(hass)
    second = await add_other_speaker(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/home/set",
            "daily_minutes": 1,
            "weekly_minutes": None,
            "warn_minutes": 0,
        }
    )
    res = await client.receive_json()
    assert res["success"], res
    assert {s["name"] for s in res["result"]["speakers"]} == {"Kids Room", "Den"}

    # Two speakers playing count twice: a minute of the home's time in 30 seconds.
    for _ in range(3):
        await advance(hass, freezer, 15)
    for entry in (first, second):
        decision = entry.runtime_data.decision
        assert (decision.state, decision.reason) == ("enforcing", "home_daily")
    await advance(hass, freezer, 5)
    paused = {c.data["entity_id"] for c in calls["media_pause"]}
    assert {SPEAKER, OTHER} <= paused

    # Extra time for the whole home lets music play again.
    await client.send_json_auto_id({"type": f"{DOMAIN}/home/extension", "minutes": 30})
    res = await client.receive_json()
    assert res["result"]["home"]["extension_minutes"] == 30
    await hass.async_block_till_done()
    assert first.runtime_data.decision.state == "ok"


async def test_weekly_summary(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls
) -> None:
    # A Sunday ahead of now: time listeners only fire forwards. (Websocket logins
    # fail under a frozen clock, so the setting is saved directly.)
    freezer.move_to(local(2030, 11, 3, 17, 30))
    sent = async_mock_service(hass, "notify", "mobile_app_parent_phone")
    set_speaker(hass)
    entry = await setup(hass)
    home = get_home(hass)
    home.set_settings(
        HomeSettings.from_dict({"summary": ["notify.mobile_app_parent_phone"]})
    )
    assert entry.runtime_data.decision.state == "ok"
    for _ in range(4):
        await advance(hass, freezer, 15)
    freezer.move_to(local(2030, 11, 3, 18, 0, 0))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(sent) == 1
    assert sent[0].data["title"] == "Media Mgmt this week"
    assert sent[0].data["message"].startswith("Kids Room: 1 min, mostly Debussy")


async def test_bedtime_fade_before_quiet_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls
) -> None:
    freezer.move_to(local(2026, 11, 9, 20, 27))
    set_speaker(hass, volume=0.5)
    entry = await setup(
        hass,
        listening={"quiet_windows": "20:30-07:00 Bedtime", "bedtime_fade": 5},
    )
    assert entry.runtime_data.seconds_until_stop() == 180
    assert calls["volume_set"], "the fade should start straight away"
    await advance(hass, freezer, 90)
    level = calls["volume_set"][-1].data["volume_level"]
    assert 0.1 < level < 0.4
    await advance(hass, freezer, 95)
    assert entry.runtime_data.decision.reason == "quiet_window"
    await advance(hass, freezer, 5)
    assert calls["media_pause"]
    # The volume goes back for next time once the music has stopped.
    assert calls["volume_set"][-1].data["volume_level"] == 0.5
    assert any(
        e.get("action") == "bedtime_fade" for e in entry.runtime_data.activity.events
    )


async def test_bedtime_fade_stops_when_extra_time_is_given(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls
) -> None:
    set_speaker(hass, volume=0.5)
    entry = await setup(hass, listening={"daily_budget": 3, "bedtime_fade": 2})
    manager = entry.runtime_data
    for _ in range(5):
        await advance(hass, freezer, 15)
    assert manager._fade and manager._fade["reason"] == "bedtime"  # noqa: SLF001
    manager.grant_extension(30)
    await hass.async_block_till_done()
    assert manager._fade is None  # noqa: SLF001
    assert calls["volume_set"][-1].data["volume_level"] == 0.5


async def test_live_activity_follows_the_music(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls
) -> None:
    sent = async_mock_service(hass, "notify", "mobile_app_parent_phone")
    set_speaker(hass)
    entry = await setup(
        hass,
        listening={"daily_budget": 60},
        announcements={"live_activity": ["mobile_app_parent_phone"]},
    )
    await hass.async_block_till_done()
    assert sent, "music playing at start shows the activity"
    first = sent[-1].data
    assert first["title"] == "Kids Room"
    assert first["data"]["tag"] == f"media-mgmt-{entry.entry_id}"
    assert first["data"]["live_update"] is True
    assert first["data"]["chronometer"] is True
    count = len(sent)

    # Counting down needs no pushes.
    await advance(hass, freezer, 60)
    assert len(sent) == count

    # Extra time moves the end: one push.
    entry.runtime_data.grant_extension(15)
    await hass.async_block_till_done()
    assert len(sent) == count + 1

    set_speaker(hass, state="paused")
    await hass.async_block_till_done()
    assert sent[-1].data["data"]["critical_text"] == "Music off"
    await advance(hass, freezer, 61)
    assert sent[-1].data["message"] == "clear_notification"
    assert hass.states.get(f"sensor.media_mgmt_{P}_enforcement_state").state == "ok"


async def test_settings_include_phones_and_fade(
    hass: HomeAssistant, hass_ws_client, calls
) -> None:
    async_mock_service(hass, "notify", "mobile_app_parent_phone")
    set_speaker(hass)
    entry = await setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/settings/set",
            "entry_id": entry.entry_id,
            "bedtime_fade": 10,
            "live_activity": ["mobile_app_parent_phone"],
        }
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/settings/get", "entry_id": entry.entry_id}
    )
    res = (await client.receive_json())["result"]
    assert res["bedtime_fade"] == 10
    assert res["live_activity"] == ["mobile_app_parent_phone"]
    assert {"service": "mobile_app_parent_phone", "name": "parent phone"} in res[
        "phones"
    ]
    assert entry.runtime_data.bedtime_fade == 10
    await client.send_json_auto_id({"type": f"{DOMAIN}/profiles"})
    profiles = (await client.receive_json())["result"]
    assert profiles["home"]["active"] is False
    assert profiles["profiles"][0]["bedtime_fade"] == 10
