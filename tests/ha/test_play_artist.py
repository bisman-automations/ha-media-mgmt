"""Playing an artist: finding the Music Assistant player, the play_artist action, voice, saved artists."""

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from homeassistant.core import Context, HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    intent,
)
from tests.ha.test_integration import ALL_FEATURES, SPEAKER, advance, set_speaker, setup

DOMAIN = "media_mgmt"
MA_PLAYER = "media_player.kids_room_ma"
SEARCH = {
    "artists": [
        {
            "media_type": "artist",
            "name": "Brahms Tribute Band",
            "uri": "spotify--x://artist/9",
            "image": None,
        },
        {
            "media_type": "artist",
            "name": "Johannes Brahms",
            "uri": "spotify--x://artist/1",
            "image": "http://img/1",
        },
    ],
    "albums": [],
    "tracks": [],
    "playlists": [],
    "radio": [],
    "audiobooks": [],
    "podcasts": [],
}


def ma_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain="music_assistant", title="Music Assistant")
    entry.add_to_hass(hass)
    return entry


def add_ma_player(
    hass,
    entity_registry,
    unique_id,
    entry,
    object_id="kids_room_ma",
    name="Kids Room (MA)",
    state="idle",
    **attrs,
):
    reg = entity_registry.async_get_or_create(
        "media_player",
        "music_assistant",
        unique_id,
        suggested_object_id=object_id,
        config_entry=entry,
    )
    hass.states.async_set(
        reg.entity_id,
        state,
        {"friendly_name": name, "supported_features": ALL_FEATURES, **attrs},
    )
    return reg.entity_id


def mock_ma(hass, search=SEARCH):
    return (
        async_mock_service(hass, "music_assistant", "play_media"),
        async_mock_service(
            hass,
            "music_assistant",
            "search",
            response=search,
            supports_response=SupportsResponse.ONLY,
        ),
    )


async def play(hass, **data):
    return await hass.services.async_call(
        DOMAIN, "play_artist", data, blocking=True, return_response=True
    )


# ---- finding the Music Assistant player ------------------------------------------------


async def test_sonos_found_by_its_sonos_id(
    hass: HomeAssistant, calls, entity_registry: er.EntityRegistry
) -> None:
    sonos = entity_registry.async_get_or_create(
        "media_player",
        "sonos",
        "RINCON_000E58ABCDEF01400",
        suggested_object_id="kids_room",
    )
    assert sonos.entity_id == SPEAKER
    set_speaker(hass, state="idle", title=None)
    entry = ma_entry(hass)
    add_ma_player(hass, entity_registry, "RINCON_000E58ABCDEF01400", entry)
    profile = await setup(hass)
    link = profile.runtime_data.ma_link
    assert (link.entity_id, link.method, link.config_entry_id) == (
        MA_PLAYER,
        "sonos",
        entry.entry_id,
    )


async def test_homepod_found_by_airplay_mac(
    hass: HomeAssistant,
    calls,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    host = MockConfigEntry(domain="apple_tv")
    host.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=host.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "AA:BB:CC:DD:EE:0F")},
        name="Kids Room",
    )
    entity_registry.async_get_or_create(
        "media_player",
        "apple_tv",
        "homepod-1",
        suggested_object_id="kids_room",
        device_id=device.id,
        config_entry=host,
    )
    set_speaker(hass, state="idle", title=None)
    add_ma_player(
        hass, entity_registry, "apaabbccddee0f", ma_entry(hass), name="Bedroom HomePod"
    )
    profile = await setup(hass)
    assert profile.runtime_data.ma_link.method == "airplay"
    assert profile.runtime_data.ma_link.entity_id == MA_PLAYER


async def test_found_by_entity_id_then_name_then_area(
    hass: HomeAssistant,
    calls,
    entity_registry: er.EntityRegistry,
    area_registry: ar.AreaRegistry,
    freezer,
) -> None:
    speaker = entity_registry.async_get_or_create(
        "media_player", "demo", "kids", suggested_object_id="kids_room"
    )
    set_speaker(hass, state="idle", title=None)
    entry = ma_entry(hass)
    # Music Assistant's Home Assistant players provider uses the entity ID.
    add_ma_player(
        hass,
        entity_registry,
        SPEAKER,
        entry,
        object_id="hass_kids",
        name="Something else",
    )
    profile = await setup(hass)
    manager = profile.runtime_data
    assert manager.ma_link.method == "entity_id"

    # Same name.
    entity_registry.async_remove("media_player.hass_kids")
    await hass.async_block_till_done()
    add_ma_player(
        hass, entity_registry, "abc123", entry, object_id="kids_ma", name="Kids Room"
    )
    await advance(
        hass, freezer, 15
    )  # named just after it was added: found on the next check
    assert (manager.ma_link.entity_id, manager.ma_link.method) == (
        "media_player.kids_ma",
        "name",
    )

    # Only one in the speaker's area.
    entity_registry.async_remove("media_player.kids_ma")
    room = area_registry.async_create("Playroom")
    entity_registry.async_update_entity(speaker.entity_id, area_id=room.id)
    other = add_ma_player(
        hass, entity_registry, "zzz", entry, object_id="playroom_ma", name="Corner"
    )
    entity_registry.async_update_entity(other, area_id=room.id)
    await hass.async_block_till_done()
    assert (manager.ma_link.entity_id, manager.ma_link.method) == (other, "area")


async def test_picked_by_hand_wins_and_a_missing_one_is_reported(
    hass: HomeAssistant, calls, entity_registry: er.EntityRegistry
) -> None:
    set_speaker(hass, state="idle", title=None)
    entry = ma_entry(hass)
    add_ma_player(
        hass, entity_registry, "abc", entry, object_id="kids_ma", name="Kids Room"
    )
    picked = add_ma_player(
        hass, entity_registry, "def", entry, object_id="garage", name="Garage"
    )
    profile = await _setup_with_player(hass, picked)
    manager = profile.runtime_data
    assert (manager.ma_link.entity_id, manager.ma_link.method) == (picked, "manual")

    hass.config_entries.async_update_entry(
        profile,
        options={
            **profile.options,
            "playback": {"music_assistant_player": "media_player.gone"},
        },
    )
    await hass.async_block_till_done()
    assert manager.ma_link.method == "name"
    assert "isn't there any more" in manager.ma_link.detail


async def _setup_with_player(hass, picked):
    from tests.ha.test_integration import options

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kids Room",
        unique_id=SPEAKER,
        data={"media_player": SPEAKER},
        options={**options(), "playback": {"music_assistant_player": picked}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ---- the play_artist action --------------------------------------------------------------


async def test_play_artist_through_music_assistant(
    hass: HomeAssistant, calls, entity_registry: er.EntityRegistry
) -> None:
    entity_registry.async_get_or_create(
        "media_player", "sonos", "RINCON_1", suggested_object_id="kids_room"
    )
    set_speaker(hass, state="idle", title=None)
    add_ma_player(hass, entity_registry, "RINCON_1", ma_entry(hass))
    ma_play, ma_search = mock_ma(hass)
    await setup(hass, volume={"max_volume": 40})

    result = await play(
        hass, artist="Johannes Brahms", radio_mode=True, shuffle=True, volume=80
    )
    assert result["ok"] is True
    assert result["entity_id"] == MA_PLAYER
    assert result["uri"] == "spotify--x://artist/1"
    assert result["provider"] == "spotify"
    assert result["method"] == "music_assistant"
    assert ma_search[0].data["name"] == "Johannes Brahms"
    assert ma_play[0].data == {
        "entity_id": MA_PLAYER,
        "media_id": "spotify--x://artist/1",
        "media_type": "artist",
        "enqueue": "replace",
        "radio_mode": True,
    }
    # The volume cap applies, and volume and shuffle go to the Music Assistant player.
    assert calls["volume_set"][-1].data == {"entity_id": MA_PLAYER, "volume_level": 0.4}
    assert calls["shuffle_set"][-1].data == {"entity_id": MA_PLAYER, "shuffle": True}
    # Logged for the sidebar app.
    manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    last = manager.activity.events[-1]
    assert last["type"] == "play_request" and last["ok"] is True


async def test_not_found_and_refusals(
    hass: HomeAssistant, calls, entity_registry: er.EntityRegistry, freezer
) -> None:
    entity_registry.async_get_or_create(
        "media_player",
        "music_assistant",
        "kids",
        suggested_object_id="kids_room",
        config_entry=ma_entry(hass),
    )
    set_speaker(hass, state="idle", title=None)
    ma_play, _ = mock_ma(hass, search={"artists": []})
    entry = await setup(hass, filter={"blocked_artists": ["Baby Shark Band"]})

    result = await play(hass, artist="Nobody At All")
    assert result["ok"] is False and result["reason"] == "not_found"

    result = await play(hass, artist="baby shark band")
    assert result["ok"] is False and result["reason"] == "blocked"

    # Without asking for a response, a refusal is an error the automation sees.
    with pytest.raises(HomeAssistantError, match="blocked"):
        await hass.services.async_call(
            DOMAIN, "play_artist", {"artist": "Baby Shark Band"}, blocking=True
        )

    manager = entry.runtime_data
    manager.force_block()
    await hass.async_block_till_done()
    result = await play(hass, artist="Brahms")
    assert result["reason"] == "limit" and "stopped for now" in result["message"]

    # Adult mode lifts the rules.
    manager.set_adult_mode(True)
    await hass.async_block_till_done()
    ma_search_ok = async_mock_service(
        hass,
        "music_assistant",
        "search",
        supports_response=SupportsResponse.ONLY,
        response={
            "artists": [
                {
                    "media_type": "artist",
                    "name": "Baby Shark Band",
                    "uri": "x://artist/7",
                }
            ]
        },
    )
    result = await play(hass, artist="Baby Shark Band")
    assert ma_search_ok
    assert result["ok"] is True
    assert ma_play


async def test_homepod_without_music_assistant_says_how_to_fix(
    hass: HomeAssistant, calls, entity_registry: er.EntityRegistry
) -> None:
    entity_registry.async_get_or_create(
        "media_player", "apple_tv", "hp", suggested_object_id="kids_room"
    )
    set_speaker(hass, state="idle", title=None)
    await setup(hass)
    result = await play(hass, artist="Brahms")
    assert result["reason"] == "unsupported"
    assert "AirPlay" in result["message"]
    assert calls["play_media"] == []


async def test_sonos_without_music_assistant_uses_a_favourite_or_share_link(
    hass: HomeAssistant, calls, entity_registry: er.EntityRegistry
) -> None:
    entity_registry.async_get_or_create(
        "media_player", "sonos", "RINCON_2", suggested_object_id="kids_room"
    )
    set_speaker(
        hass, state="idle", title=None, source_list=["Brahms Lullabies", "Radio 1"]
    )
    await setup(hass)
    result = await play(hass, artist="Brahms")
    assert result["ok"] and result["method"] == "favorite"
    assert calls["select_source"][-1].data["source"] == "Brahms Lullabies"

    result = await play(
        hass,
        artist="Taylor Swift",
        uri="https://open.spotify.com/artist/06HL4z0CvFAxyc27GXpf02",
    )
    assert result["ok"] and result["method"] == "share_link"
    assert calls["play_media"][-1].data["media_content_type"] == "music"

    result = await play(hass, artist="Nobody")
    assert result["reason"] == "unsupported" and "Sonos favourite" in result["message"]


async def test_speaker_by_name_area_and_errors(
    hass: HomeAssistant,
    calls,
    entity_registry: er.EntityRegistry,
    area_registry: ar.AreaRegistry,
) -> None:
    room = area_registry.async_create("Playroom", aliases={"play room"})
    reg = entity_registry.async_get_or_create(
        "media_player", "music_assistant", "kids", suggested_object_id="kids_room"
    )
    entity_registry.async_update_entity(reg.entity_id, area_id=room.id)
    set_speaker(hass, state="idle", title=None)
    ma_play = async_mock_service(hass, "music_assistant", "play_media")
    await setup(hass)
    assert (await play(hass, artist="Brahms", speaker="kids room speaker"))["ok"]
    assert (await play(hass, artist="Brahms", speaker="Play Room"))["ok"]
    assert (await play(hass, artist="Brahms", area_id=room.id))["ok"]
    assert len(ma_play) == 3
    result = await play(hass, artist="Brahms", speaker="Garage")
    assert result["reason"] == "speaker_not_found"


# ---- the Music Assistant player does the enforcing while it plays -----------------------


async def test_blocked_song_skipped_on_the_music_assistant_player(
    hass: HomeAssistant, calls, entity_registry: er.EntityRegistry, freezer
) -> None:
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    entity_registry.async_get_or_create(
        "media_player", "sonos", "RINCON_3", suggested_object_id="kids_room"
    )
    set_speaker(hass, state="idle", title=None)
    entry = ma_entry(hass)
    await setup(hass, filter={"blocked_artists": ["Baby Shark Band"]})
    add_ma_player(hass, entity_registry, "RINCON_3", entry)
    await hass.async_block_till_done()
    hass.states.async_set(
        MA_PLAYER,
        "playing",
        {
            "friendly_name": "Kids Room (MA)",
            "supported_features": ALL_FEATURES,
            "media_title": "Baby Shark",
            "media_artist": "Baby Shark Band",
            "volume_level": 0.2,
        },
    )
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["media_next_track"], "the blocked song wasn't skipped"
    assert calls["media_next_track"][-1].data["entity_id"] == MA_PLAYER
    diag_manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    assert diag_manager.player.via_twin


# ---- schedules use the same path --------------------------------------------------------


async def test_schedule_plays_artist_through_music_assistant_player(
    hass: HomeAssistant, calls, entity_registry: er.EntityRegistry
) -> None:
    entity_registry.async_get_or_create(
        "media_player", "sonos", "RINCON_4", suggested_object_id="kids_room"
    )
    set_speaker(hass, state="idle", title=None)
    add_ma_player(hass, entity_registry, "RINCON_4", ma_entry(hass))
    ma_play, _ = mock_ma(hass)
    entry = await setup(hass)
    manager = entry.runtime_data
    sched = manager.save_schedule(
        {
            "name": "Bedtime",
            "days": [0],
            "start": "19:30",
            "stop": "20:30",
            "play_kind": "artist",
            "play_value": "Johannes Brahms",
            "volume": 20,
        }
    )
    assert await manager.async_start_schedule(sched)
    assert ma_play[-1].data["entity_id"] == MA_PLAYER
    assert ma_play[-1].data["media_id"] == "spotify--x://artist/1"
    assert calls["volume_set"][-1].data["entity_id"] == MA_PLAYER


# ---- saved artists ----------------------------------------------------------------------


async def test_saved_artists_websocket(
    hass: HomeAssistant,
    hass_ws_client,
    hass_admin_user,
    calls,
    entity_registry: er.EntityRegistry,
) -> None:
    entity_registry.async_get_or_create(
        "media_player",
        "music_assistant",
        "kids",
        suggested_object_id="kids_room",
        config_entry=ma_entry(hass),
    )
    set_speaker(hass, state="idle", title=None)
    ma_play, _ = mock_ma(hass)
    entry = await setup(hass)
    client = await hass_ws_client(hass)

    async def call(**msg):
        await client.send_json_auto_id(msg)
        return await client.receive_json()

    res = await call(type=f"{DOMAIN}/artists/search", query="Brahms")
    assert res["success"], res
    assert res["result"]["items"][1]["uri"] == "spotify--x://artist/1"

    # Saved from what played before: Music Assistant finds the exact artist.
    res = await call(
        type=f"{DOMAIN}/artists/save",
        artist={"name": "Johannes Brahms", "aliases": "Brahms"},
        find=True,
    )
    assert res["success"], res
    saved = res["result"]["artist"]
    assert saved["uri"] == "spotify--x://artist/1" and saved["image"] == "http://img/1"

    res = await call(type=f"{DOMAIN}/artists/list")
    assert [a["name"] for a in res["result"]["artists"]] == ["Johannes Brahms"]
    assert res["result"]["search"] is True
    assert res["result"]["speakers"][0]["music_assistant"] is True

    # Turn radio on, then play it by its other name.
    res = await call(type=f"{DOMAIN}/artists/save", artist={**saved, "radio": True})
    assert res["result"]["artist"]["id"] == saved["id"]
    result = await play(hass, artist="brahms")
    assert result["ok"] and result["radio"] is True
    assert ma_play[-1].data["media_id"] == "spotify--x://artist/1"

    res = await call(
        type=f"{DOMAIN}/artists/play", artist=saved["id"], entry_id=entry.entry_id
    )
    assert res["success"], res
    assert res["result"]["ok"] is True

    # The optional entities exist but start turned off.
    select = entity_registry.async_get("select.media_mgmt_kids_room_play_artist")
    button = next(
        e
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        if e.unique_id.endswith(f"play_artist_{saved['id']}")
    )
    assert select.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert button.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    # Only parents with access may change saved artists.
    admin_groups = hass_admin_user.groups
    hass_admin_user.groups = []
    res = await call(type=f"{DOMAIN}/artists/delete", artist_id=saved["id"])
    assert res["error"]["code"] == "unauthorized"
    hass_admin_user.groups = admin_groups
    res = await call(type=f"{DOMAIN}/artists/delete", artist_id=saved["id"])
    assert res["success"]
    await hass.async_block_till_done()
    assert not [
        e
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        if e.unique_id.endswith(f"play_artist_{saved['id']}")
    ]


async def test_profile_shows_music_assistant_link(
    hass: HomeAssistant, hass_ws_client, calls, entity_registry: er.EntityRegistry
) -> None:
    entity_registry.async_get_or_create(
        "media_player", "sonos", "RINCON_5", suggested_object_id="kids_room"
    )
    set_speaker(hass, state="idle", title=None)
    add_ma_player(hass, entity_registry, "RINCON_5", ma_entry(hass))
    entry = await setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/profiles"})
    profile = (await client.receive_json())["result"]["profiles"][0]
    assert (
        profile["ma_link"]["entity_id"] == MA_PLAYER
        and profile["ma_link"]["method"] == "sonos"
    )

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/settings/set",
            "entry_id": entry.entry_id,
            "music_assistant_player": SPEAKER,
        }
    )
    assert not (await client.receive_json())["success"]  # not a Music Assistant player

    from custom_components.media_mgmt.diagnostics import (
        async_get_config_entry_diagnostics,
    )
    from homeassistant.components.diagnostics import REDACTED

    set_speaker(hass, entity_picture="/api/media_player_proxy/x?token=abc123")
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["player"]["music_assistant"]["method"] == "sonos"
    # Picture URLs carry a token, so they never leave in diagnostics.
    attributes = diag["player"]["state"]["attributes"]
    assert attributes["entity_picture"] == REDACTED
    assert "token=" not in str(diag)


# ---- voice and AI assistants ------------------------------------------------------------


async def test_intent_plays_in_the_satellites_room(
    hass: HomeAssistant,
    calls,
    entity_registry: er.EntityRegistry,
    area_registry: ar.AreaRegistry,
) -> None:
    room = area_registry.async_create("Playroom")
    reg = entity_registry.async_get_or_create(
        "media_player", "music_assistant", "kids", suggested_object_id="kids_room"
    )
    entity_registry.async_update_entity(reg.entity_id, area_id=room.id)
    set_speaker(hass, state="idle", title=None)
    ma_play, _ = mock_ma(hass)
    ma_entry(hass)
    await setup(hass)
    response = await intent.async_handle(
        hass,
        "test",
        "MediaMgmtPlayArtist",
        {
            "artist": {"value": "Johannes Brahms"},
            "preferred_area_id": {"value": room.id},
        },
        context=Context(),
    )
    assert response.response_type is intent.IntentResponseType.ACTION_DONE
    assert "Johannes Brahms" in response.speech["plain"]["speech"]
    assert ma_play[-1].data["entity_id"] == SPEAKER

    response = await intent.async_handle(
        hass,
        "test",
        "MediaMgmtPlayArtist",
        {"artist": {"value": "Brahms"}, "speaker": {"value": "Garage"}},
    )
    assert response.response_type is intent.IntentResponseType.ERROR


async def test_ai_assistants_get_the_tool(
    hass: HomeAssistant, calls, entity_registry: er.EntityRegistry
) -> None:
    pytest.importorskip("homeassistant.components.llm")
    from homeassistant.components.homeassistant.exposed_entities import (
        async_expose_entity,
    )
    from homeassistant.helpers import llm
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "llm", {})
    set_speaker(hass, state="idle", title=None)
    await setup(hass)
    context = llm.LLMContext(
        platform="test",
        context=Context(),
        language="en",
        assistant="conversation",
        device_id=None,
    )
    async_expose_entity(hass, "conversation", SPEAKER, False)
    api = await llm.async_get_api(hass, llm.LLM_API_ASSIST, context)
    names = [t.name for t in api.tools]
    assert "media_mgmt__MediaMgmtPlayArtist" not in names  # the speaker isn't exposed

    async_expose_entity(hass, "conversation", SPEAKER, True)
    api = await llm.async_get_api(hass, llm.LLM_API_ASSIST, context)
    tool = next(t for t in api.tools if t.name == "media_mgmt__MediaMgmtPlayArtist")
    assert "artist" in str(tool.parameters.schema)
    assert "preferred_area_id" not in str(tool.parameters.schema)
    assert "Kids Room" in api.api_prompt


async def test_blueprint_plays_by_text(
    hass: HomeAssistant, calls, entity_registry: er.EntityRegistry, tmp_path
) -> None:
    """The conversation blueprint: "play Brahms on kids room", and the reply says what happened."""
    pytest.importorskip(
        "hassil", reason="the conversation integration's requirements aren't installed"
    )
    from pathlib import Path
    import shutil

    from homeassistant.components import conversation
    from homeassistant.setup import async_setup_component

    entity_registry.async_get_or_create(
        "media_player",
        "music_assistant",
        "kids",
        suggested_object_id="kids_room",
        config_entry=ma_entry(hass),
    )
    set_speaker(hass, state="idle", title=None)
    ma_play, _ = mock_ma(hass)
    await setup(hass)

    hass.config.config_dir = str(tmp_path)
    target = tmp_path / "blueprints" / "automation" / "media_mgmt"
    target.mkdir(parents=True)
    shutil.copy(
        Path(__file__).parents[2] / "blueprints/automation/media_mgmt/play_artist.yaml",
        target,
    )
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": "media_mgmt/play_artist.yaml",
                    "input": {"radio_mode": True},
                }
            }
        },
    )
    await hass.async_block_till_done()

    result = await conversation.async_converse(
        hass, "play Brahms on the kids room", None, Context(), language="en"
    )
    assert (
        ma_play[-1].data["media_id"] == "spotify--x://artist/9"
    )  # Brahms Tribute Band: the top close result
    assert ma_play[-1].data["radio_mode"] is True
    assert (
        result.response.speech["plain"]["speech"]
        == "Playing Brahms Tribute Band on Kids Room"
    )

    result = await conversation.async_converse(
        hass, "play Brahms on the garage", None, Context(), language="en"
    )
    assert "garage" in result.response.speech["plain"]["speech"].lower()

    # Without a speaker: the only managed speaker.
    count = len(ma_play)
    result = await conversation.async_converse(
        hass, "put on some Johannes Brahms", None, Context(), language="en"
    )
    assert (
        len(ma_play) == count + 1
        and ma_play[-1].data["media_id"] == "spotify--x://artist/1"
    )
