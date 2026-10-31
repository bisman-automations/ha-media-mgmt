"""The sidebar app's websocket API: everything it shows and changes."""

from homeassistant.core import HomeAssistant
from tests.ha.test_integration import SPEAKER, P, set_speaker, setup

DOMAIN = "media_mgmt"


async def test_profile_settings_and_schedule(
    hass: HomeAssistant, hass_ws_client, calls
) -> None:
    set_speaker(hass, title="Lullaby", artist="Brahms")
    entry = await setup(hass)
    client = await hass_ws_client(hass)

    async def call(**msg):
        await client.send_json_auto_id(msg)
        return await client.receive_json()

    res = await call(type=f"{DOMAIN}/profiles")
    assert res["success"]
    profile = res["result"]["profiles"][0]
    assert profile["entity_id"] == SPEAKER
    assert profile["media"]["artist"] == "Brahms"
    # When the song started, so the dashboard lists recent speakers first.
    assert profile["last_played"] == (entry.runtime_data.activity.last_play["t"])
    assert profile["last_played"]

    # Played music lists the artist, to pick for a schedule.
    res = await call(type=f"{DOMAIN}/history", entry_id=entry.entry_id, view="artists")
    assert [a["artist"] for a in res["result"]["items"]] == ["Brahms"]

    # Rules are changed live, without reloading the profile.
    manager = entry.runtime_data
    res = await call(
        type=f"{DOMAIN}/settings/set",
        entry_id=entry.entry_id,
        daily_budget=45,
        quiet_windows="20:30-07:00 Bedtime",
        max_volume=60,
    )
    assert res["success"], res
    await hass.async_block_till_done()
    assert entry.runtime_data is manager
    assert manager.daily_budget == 45 and manager.max_volume == 60
    assert manager.quiet_windows[0].label == "Bedtime"

    res = await call(
        type=f"{DOMAIN}/settings/set", entry_id=entry.entry_id, quiet_windows="nonsense"
    )
    assert not res["success"]

    res = await call(
        type=f"{DOMAIN}/filter/update",
        entry_id=entry.entry_id,
        kind="track",
        value="Baby Shark",
        add=True,
    )
    assert res["result"]["filter"]["track"] == ["Baby Shark"]

    # A nightly bedtime schedule, saved and listed with its next run.
    res = await call(
        type=f"{DOMAIN}/schedule/save",
        entry_id=entry.entry_id,
        schedule={
            "name": "Bedtime music",
            "days": [0, 1, 2, 3, 4, 5, 6],
            "start": "19:30",
            "stop": "20:30",
            "play_kind": "artist",
            "play_value": "Brahms",
            "volume": 20,
            "fade_minutes": 10,
        },
    )
    assert res["success"], res
    listed = res["result"]["schedules"][0]
    assert listed["play_value"] == "Brahms" and listed["next_run"]

    res = await call(
        type=f"{DOMAIN}/schedule/save",
        entry_id=entry.entry_id,
        schedule={
            "name": "Broken",
            "days": [0],
            "start": "19:30",
            "stop": "19:30",
            "play_value": "Brahms",
        },
    )
    assert not res["success"]

    res = await call(
        type=f"{DOMAIN}/schedule/delete",
        entry_id=entry.entry_id,
        schedule_id=listed["id"],
    )
    assert res["result"]["schedules"] == []


async def test_add_and_remove_speakers(
    hass: HomeAssistant, hass_ws_client, calls
) -> None:
    set_speaker(hass)
    hass.states.async_set(
        "media_player.living_room", "idle", {"friendly_name": "Living Room"}
    )
    await setup(hass)
    client = await hass_ws_client(hass)

    async def call(**msg):
        await client.send_json_auto_id(msg)
        return await client.receive_json()

    res = await call(type=f"{DOMAIN}/speakers/candidates")
    assert [p["entity_id"] for p in res["result"]["players"]] == [
        "media_player.living_room"
    ]

    res = await call(
        type=f"{DOMAIN}/speakers/add", entity_id="media_player.living_room"
    )
    assert res["success"], res
    await hass.async_block_till_done()
    added = hass.config_entries.async_get_entry(res["result"]["entry_id"])
    assert added.title == "Living Room"
    # Starts with no limits and nothing blocked.
    assert added.runtime_data.daily_budget == 0
    assert added.runtime_data.filter.empty
    assert (
        hass.states.get("sensor.media_mgmt_living_room_enforcement_state").state == "ok"
    )

    res = await call(
        type=f"{DOMAIN}/speakers/add", entity_id="media_player.living_room"
    )
    assert res["error"]["code"] == "already_configured"
    res = await call(type=f"{DOMAIN}/speakers/add", entity_id="media_player.nope")
    assert res["error"]["code"] == "not_found"

    res = await call(type=f"{DOMAIN}/speakers/remove", entry_id=added.entry_id)
    assert res["success"]
    await hass.async_block_till_done()
    assert hass.config_entries.async_get_entry(added.entry_id) is None
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_parents_need_access(
    hass: HomeAssistant, hass_ws_client, hass_admin_user, calls
) -> None:
    set_speaker(hass)
    entry = await setup(hass)
    hass_admin_user.groups = []  # now an ordinary user, like a child's login
    client = await hass_ws_client(hass)

    async def call(**msg):
        await client.send_json_auto_id(msg)
        return await client.receive_json()

    res = await call(type=f"{DOMAIN}/access/me")
    assert res["result"]["allowed"] is False
    for msg in (
        {"type": f"{DOMAIN}/profiles"},
        {
            "type": f"{DOMAIN}/settings/set",
            "entry_id": entry.entry_id,
            "daily_budget": 600,
        },
        {"type": f"{DOMAIN}/speakers/candidates"},
    ):
        res = await call(**msg)
        assert not res["success"], msg
        assert res["error"]["code"] == "unauthorized"
    # Nor from a regular dashboard.
    import pytest

    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": f"switch.media_mgmt_{P}_adult_mode"},
            blocking=True,
            context=__import__("homeassistant.core", fromlist=["Context"]).Context(
                user_id=hass_admin_user.id
            ),
        )
