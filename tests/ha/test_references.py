"""Following renamed entities, repair issues for deleted ones, and Reconfigure.

The bug these cover: changing the speaker's entity ID (Settings → Entities →
the speaker → Entity ID) left the profile watching the old ID, which has no
state any more, so music on the speaker was never counted, limited, quieted
or filtered, and nothing said so.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.media_mgmt.const import DOMAIN
from custom_components.media_mgmt.references import (
    ISSUE_MA_PLAYER_MISSING,
    ISSUE_SPEAKER_MISSING,
    async_check_issues,
    entity_missing,
    issue_id,
    referenced_ids,
    renamed_options,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from tests.ha.test_integration import SPEAKER, options, set_speaker, setup

NEW_SPEAKER = "media_player.playroom"
MA_PLAYER = "media_player.kids_room_ma"


def register_speaker(hass: HomeAssistant, entity_id: str = SPEAKER) -> er.RegistryEntry:
    """Put the speaker in the entity registry, as a real integration would."""
    object_id = entity_id.split(".", 1)[1]
    return er.async_get(hass).async_get_or_create(
        "media_player", "sonos", f"RINCON_{object_id}", suggested_object_id=object_id
    )


def register_ma_player(hass: HomeAssistant) -> er.RegistryEntry:
    return er.async_get(hass).async_get_or_create(
        "media_player",
        "music_assistant",
        "ma_kids_room",
        suggested_object_id="kids_room_ma",
    )


def issue(hass: HomeAssistant, kind: str, entry_id: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id(kind, entry_id))


# ---- renames ----------------------------------------------------------------------


async def test_renamed_speaker_is_followed(hass: HomeAssistant, calls) -> None:
    """Changing the speaker's entity ID keeps the profile working on it."""
    register_speaker(hass)
    set_speaker(hass, volume=0.3)
    entry = await setup(hass, volume={"max_volume": 40})
    assert entry.runtime_data.entity_id == SPEAKER

    attributes = dict(hass.states.get(SPEAKER).attributes)
    er.async_get(hass).async_update_entity(SPEAKER, new_entity_id=NEW_SPEAKER)
    # The speaker's integration now writes its state under the new ID.
    hass.states.async_remove(SPEAKER)
    hass.states.async_set(NEW_SPEAKER, "playing", attributes)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["media_player"] == NEW_SPEAKER
    assert entry.unique_id == NEW_SPEAKER
    manager = entry.runtime_data
    assert manager.entity_id == NEW_SPEAKER
    assert manager.player.is_playing
    # No repair issue: it was renamed, not deleted.
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is None

    # The rules act on the renamed speaker: turned up too loud, it's turned
    # back down (before 1.7.0 nothing happened).
    calls["volume_set"].clear()
    hass.states.async_set(NEW_SPEAKER, "playing", {**attributes, "volume_level": 0.9})
    await hass.async_block_till_done()
    assert calls["volume_set"], "the renamed speaker isn't managed"
    assert calls["volume_set"][-1].data["entity_id"] == NEW_SPEAKER
    assert calls["volume_set"][-1].data["volume_level"] == 0.4


async def test_renamed_settings_entities_are_followed(
    hass: HomeAssistant, calls
) -> None:
    """The Music Assistant player and the announcement speakers follow renames."""
    register_speaker(hass)
    register_ma_player(hass)
    other = er.async_get(hass).async_get_or_create(
        "media_player", "cast", "kitchen", suggested_object_id="kitchen"
    )
    set_speaker(hass)
    entry = await setup(
        hass,
        playback={"music_assistant_player": MA_PLAYER},
        announcements={"announce_players": [other.entity_id, "media_player.hall"]},
    )
    registry = er.async_get(hass)
    registry.async_update_entity(MA_PLAYER, new_entity_id="media_player.ma_renamed")
    registry.async_update_entity(other.entity_id, new_entity_id="media_player.cook")
    await hass.async_block_till_done()

    assert entry.options["playback"]["music_assistant_player"] == (
        "media_player.ma_renamed"
    )
    assert entry.options["announcements"]["announce_players"] == [
        "media_player.cook",
        "media_player.hall",
    ]
    # Applied live: the same manager, with the new settings.
    assert entry.runtime_data.options["music_assistant_player"] == (
        "media_player.ma_renamed"
    )


async def test_rename_does_not_take_another_profiles_unique_id(
    hass: HomeAssistant, calls
) -> None:
    """A unique ID another profile has stays with that profile."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    other = MockConfigEntry(
        domain=DOMAIN, unique_id=NEW_SPEAKER, data={"media_player": "x.y"}
    )
    other.add_to_hass(hass)
    register_speaker(hass)
    set_speaker(hass)
    entry = await setup(hass)
    er.async_get(hass).async_update_entity(SPEAKER, new_entity_id=NEW_SPEAKER)
    await hass.async_block_till_done()
    assert entry.data["media_player"] == NEW_SPEAKER
    assert entry.unique_id == SPEAKER


def test_renamed_options_only_touches_entity_settings() -> None:
    opts = options(
        playback={"music_assistant_player": "media_player.a"},
        announcements={"announce_tts": "tts.a", "announce_players": ["media_player.a"]},
    )
    assert renamed_options(opts, "media_player.zzz", "media_player.b") is None
    new = renamed_options(opts, "media_player.a", "media_player.b")
    assert new is not None
    assert new["playback"]["music_assistant_player"] == "media_player.b"
    assert new["announcements"]["announce_players"] == ["media_player.b"]
    assert new["announcements"]["announce_tts"] == "tts.a"
    # The original is left alone.
    assert opts["playback"]["music_assistant_player"] == "media_player.a"


# ---- repair issues ------------------------------------------------------------------


async def test_deleted_speaker_raises_an_issue(hass: HomeAssistant, calls) -> None:
    register_speaker(hass)
    set_speaker(hass)
    entry = await setup(hass)
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is None

    er.async_get(hass).async_remove(SPEAKER)
    hass.states.async_remove(SPEAKER)
    await hass.async_block_till_done()
    found = issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id)
    assert found is not None
    assert found.is_fixable
    assert found.severity is ir.IssueSeverity.ERROR
    assert found.translation_placeholders == {
        "profile": "Kids Room",
        "entity_id": SPEAKER,
    }

    # It comes back (added again with the same ID): the issue goes away.
    register_speaker(hass)
    set_speaker(hass)
    await hass.async_block_till_done()
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is None


async def test_unavailable_speaker_is_not_missing(hass: HomeAssistant, calls) -> None:
    """A registered speaker without a state (integration not loaded) is fine."""
    register_speaker(hass)
    entry = await setup(hass)
    assert entity_missing(hass, SPEAKER) is False
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is None


async def test_issues_wait_for_home_assistant_to_start(
    hass: HomeAssistant, calls
) -> None:
    """Entities from integrations that load later aren't reported at startup."""
    hass.set_state(CoreState.starting)
    entry = await setup(hass)  # the speaker isn't there yet
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is None
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is not None


async def test_unload_and_remove_clear_issues(hass: HomeAssistant, calls) -> None:
    entry = await setup(hass)  # no speaker at all
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is None
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is not None
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is None


async def _fix(
    hass: HomeAssistant, hass_client, entry_id: str, kind: str
) -> tuple[Any, dict[str, Any]]:
    assert await async_setup_component(hass, "repairs", {})
    await hass.async_block_till_done()
    client = await hass_client()
    resp = await client.post(
        "/api/repairs/issues/fix",
        json={"handler": DOMAIN, "issue_id": issue_id(kind, entry_id)},
    )
    assert resp.status == 200, await resp.text()
    return client, await resp.json()


async def test_fix_a_deleted_speaker(hass: HomeAssistant, hass_client, calls) -> None:
    entry = await setup(hass)  # its speaker was deleted
    set_speaker(hass)
    hass.states.async_remove(SPEAKER)
    hass.states.async_set(NEW_SPEAKER, "idle", {"friendly_name": "Playroom"})
    async_check_issues(hass, entry)
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is not None

    client, flow = await _fix(hass, hass_client, entry.entry_id, ISSUE_SPEAKER_MISSING)
    assert flow["step_id"] == "pick_speaker"
    assert flow["description_placeholders"]["entity_id"] == SPEAKER
    resp = await client.post(
        f"/api/repairs/issues/fix/{flow['flow_id']}",
        json={"media_player": NEW_SPEAKER},
    )
    assert resp.status == 200
    assert (await resp.json())["type"] == "create_entry"
    await hass.async_block_till_done()

    assert entry.data["media_player"] == NEW_SPEAKER
    assert entry.unique_id == NEW_SPEAKER
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.entity_id == NEW_SPEAKER
    assert issue(hass, ISSUE_SPEAKER_MISSING, entry.entry_id) is None


async def test_fix_will_not_pick_a_managed_speaker(
    hass: HomeAssistant, hass_client, calls
) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    MockConfigEntry(
        domain=DOMAIN, unique_id=NEW_SPEAKER, data={"media_player": NEW_SPEAKER}
    ).add_to_hass(hass)
    entry = await setup(hass)
    client, flow = await _fix(hass, hass_client, entry.entry_id, ISSUE_SPEAKER_MISSING)
    resp = await client.post(
        f"/api/repairs/issues/fix/{flow['flow_id']}",
        json={"media_player": NEW_SPEAKER},
    )
    result = await resp.json()
    assert result["type"] == "form"
    assert result["errors"] == {"media_player": "speaker_taken"}
    assert entry.data["media_player"] == SPEAKER


async def test_missing_music_assistant_player(
    hass: HomeAssistant, hass_client, calls
) -> None:
    register_speaker(hass)
    set_speaker(hass)
    entry = await setup(hass, playback={"music_assistant_player": MA_PLAYER})
    found = issue(hass, ISSUE_MA_PLAYER_MISSING, entry.entry_id)
    assert found is not None
    assert found.severity is ir.IssueSeverity.WARNING

    client, flow = await _fix(
        hass, hass_client, entry.entry_id, ISSUE_MA_PLAYER_MISSING
    )
    assert flow["step_id"] == "pick_player"
    resp = await client.post(f"/api/repairs/issues/fix/{flow['flow_id']}", json={})
    assert (await resp.json())["type"] == "create_entry"
    await hass.async_block_till_done()
    # Left empty: Media Mgmt finds the speaker's Music Assistant player itself.
    assert entry.options["playback"]["music_assistant_player"] is None
    assert issue(hass, ISSUE_MA_PLAYER_MISSING, entry.entry_id) is None
    assert entry.runtime_data.options["music_assistant_player"] is None


async def test_fix_flow_for_a_deleted_profile(hass: HomeAssistant) -> None:
    """An issue left over from a deleted profile just confirms."""
    from custom_components.media_mgmt.repairs import async_create_fix_flow
    from homeassistant.components.repairs import ConfirmRepairFlow

    flow = await async_create_fix_flow(
        hass, "speaker_missing_gone", {"entry_id": "gone", "kind": "speaker_missing"}
    )
    assert isinstance(flow, ConfirmRepairFlow)


async def test_referenced_ids(hass: HomeAssistant, calls) -> None:
    entry = await setup(
        hass,
        playback={"music_assistant_player": MA_PLAYER},
        announcements={"announce_tts": "tts.x", "announce_players": ["media_player.a"]},
    )
    assert referenced_ids(entry) == {SPEAKER, MA_PLAYER, "tts.x", "media_player.a"}


# ---- reconfigure --------------------------------------------------------------------


async def test_reconfigure_changes_the_speaker(hass: HomeAssistant, calls) -> None:
    set_speaker(hass)
    hass.states.async_set(NEW_SPEAKER, "idle", {"friendly_name": "Playroom"})
    entry = await setup(hass, listening={"daily_budget": 45})
    entry.runtime_data.grant_extension(10, None, None)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["description_placeholders"] == {
        "profile": "Kids Room",
        "entity": SPEAKER,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"media_player": NEW_SPEAKER}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["media_player"] == NEW_SPEAKER
    assert entry.unique_id == NEW_SPEAKER
    manager = entry.runtime_data
    assert manager.entity_id == NEW_SPEAKER
    # Rules and today's numbers stay with the profile.
    assert manager.daily_budget == 45
    assert manager.state.extension_minutes == 10


async def test_reconfigure_rejects_a_managed_speaker(
    hass: HomeAssistant, calls
) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    MockConfigEntry(
        domain=DOMAIN, unique_id=NEW_SPEAKER, data={"media_player": NEW_SPEAKER}
    ).add_to_hass(hass)
    set_speaker(hass)
    entry = await setup(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"media_player": NEW_SPEAKER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"media_player": "speaker_taken"}
    assert entry.data["media_player"] == SPEAKER


async def test_reconfigure_with_the_same_speaker(hass: HomeAssistant, calls) -> None:
    set_speaker(hass)
    entry = await setup(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"media_player": SPEAKER}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert entry.state is ConfigEntryState.LOADED


@pytest.mark.parametrize("kind", [ISSUE_SPEAKER_MISSING, ISSUE_MA_PLAYER_MISSING])
def test_issue_translations(kind: str) -> None:
    """Every issue and fix step has its text, the same in strings.json and en.json."""
    import json
    from pathlib import Path

    root = Path(__file__).parents[2] / "custom_components" / DOMAIN
    strings = json.loads((root / "strings.json").read_text())
    assert strings == json.loads((root / "translations" / "en.json").read_text())
    text = strings["issues"][kind]
    assert "{profile}" in text["title"]
    steps = text["fix_flow"]["step"]
    step = "pick_speaker" if kind == ISSUE_SPEAKER_MISSING else "pick_player"
    assert "{entity_id}" in steps[step]["description"]
    assert steps[step]["data"] and steps[step]["data_description"]
    assert steps["confirm"]["description"]
    reconfigure = strings["config"]["step"]["reconfigure"]
    assert reconfigure["data"]["media_player"]
    assert strings["config"]["abort"]["reconfigure_successful"]
    assert strings["config"]["error"]["speaker_taken"]
