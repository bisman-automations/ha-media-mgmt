"""The sidebar app's Node tests run against real websocket answers.

tests/fixtures/panel_ws.json holds what the media_mgmt/* websocket commands
answer for a speaker that's playing, with a schedule, blocked music, a
quiet window and a whole-home limit. tests/test_panel_frontend.mjs feeds
these answers to the panel (no Home Assistant needed in the Node job) and
renders every tab.

This test makes the same calls and checks the file still has the same shape
(every key the backend sends now, at every depth), so the Node tests can't
quietly drift from the backend. After changing what a command sends, write
the file again with:

    MEDIA_MGMT_WRITE_FIXTURE=1 pytest tests/ha/test_panel_fixture.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from tests.ha.test_integration import set_speaker, setup

DOMAIN = "media_mgmt"
FIXTURE = Path(__file__).parents[1] / "fixtures" / "panel_ws.json"


def shape(value: Any) -> Any:
    """The keys of every dict at every depth (lists by their first item)."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__ if value is not None else None


def _same_shape(fixture: Any, live: Any, path: str = "$") -> list[str]:
    """Where the fixture is missing keys the backend sends now (or has extra ones)."""
    problems: list[str] = []
    if isinstance(live, dict) and isinstance(fixture, dict):
        for key in live.keys() - fixture.keys():
            problems.append(f"{path}.{key}: missing from the fixture")
        for key in fixture.keys() - live.keys():
            problems.append(f"{path}.{key}: no longer sent")
        for key in live.keys() & fixture.keys():
            problems += _same_shape(fixture[key], live[key], f"{path}.{key}")
    elif isinstance(live, list) and isinstance(fixture, list) and live and fixture:
        problems += _same_shape(fixture[0], live[0], f"{path}[0]")
    return problems


async def _answers(hass: HomeAssistant, hass_ws_client) -> dict[str, Any]:
    await hass.config.async_set_time_zone("America/Chicago")
    set_speaker(hass)
    entry = await setup(
        hass,
        listening={"daily_budget": 60, "quiet_windows": "20:30-07:00 Bedtime"},
        filter={"blocked_artists": ["Baby Shark"]},
        volume={"max_volume": 70},
    )
    client = await hass_ws_client(hass)

    async def call(**msg: Any) -> Any:
        await client.send_json_auto_id(msg)
        res = await client.receive_json()
        assert res["success"], res
        return res["result"]

    eid = entry.entry_id
    await call(
        type=f"{DOMAIN}/schedule/save",
        entry_id=eid,
        schedule={
            "name": "Bedtime music",
            "days": [0, 1, 2, 3, 4, 5, 6],
            "start": "19:30",
            "stop": "20:15",
            "play_kind": "artist",
            "play_value": "Debussy",
            "fade_minutes": 10,
        },
    )
    await call(type=f"{DOMAIN}/home/set", daily_minutes=180, weekly_minutes=None)
    # The fixture uses a stable ID instead of the random entry ID.
    raw = {
        "access/me": await call(type=f"{DOMAIN}/access/me"),
        "access/get": await call(type=f"{DOMAIN}/access/get"),
        "profiles": await call(type=f"{DOMAIN}/profiles"),
        "activity": await call(type=f"{DOMAIN}/activity", entry_id=eid),
        "analytics": await call(type=f"{DOMAIN}/analytics", entry_id=eid),
        "history/songs": await call(type=f"{DOMAIN}/history", entry_id=eid),
        "history/artists": await call(
            type=f"{DOMAIN}/history", entry_id=eid, view="artists"
        ),
        "settings/get": await call(type=f"{DOMAIN}/settings/get", entry_id=eid),
        "home/get": await call(type=f"{DOMAIN}/home/get"),
        "speakers/candidates": await call(type=f"{DOMAIN}/speakers/candidates"),
        "artists/list": await call(type=f"{DOMAIN}/artists/list"),
    }
    return json.loads(json.dumps(raw).replace(eid, "ENTRY_1"))


async def test_panel_fixture_matches_the_backend(
    hass: HomeAssistant, hass_ws_client, calls
) -> None:
    live = await _answers(hass, hass_ws_client)
    if os.environ.get("MEDIA_MGMT_WRITE_FIXTURE"):
        FIXTURE.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n")
    fixture = json.loads(FIXTURE.read_text())
    assert fixture.keys() == live.keys()
    problems = _same_shape(fixture, live)
    assert not problems, (
        "tests/fixtures/panel_ws.json is out of date; write it again "
        "(see this file's docstring):\n" + "\n".join(problems)
    )
