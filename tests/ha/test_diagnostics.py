"""Diagnostics leave nothing personal: who, phones, tokens in links.

Before 1.7.0 the speaker state's context carried the user ID of whoever last
changed the speaker, the Live Activity phones (notify services named after
people, such as notify.mobile_app_alexs_iphone) were listed, and a stream
link with a token in its query string (a Plex or Jellyfin stream, a signed
Home Assistant media link) was shown as is.
"""

from __future__ import annotations

import json

from custom_components.media_mgmt.diagnostics import (
    async_get_config_entry_diagnostics,
    scrub_urls,
)
from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import Context, HomeAssistant
from tests.ha.test_integration import SPEAKER, set_speaker, setup

USER_ID = "8a1f0c2e9b7d4e3f8a1f0c2e9b7d4e3f"
TOKEN = "s3cr3t-token-value"


async def test_nothing_personal_in_diagnostics(hass: HomeAssistant, calls) -> None:
    set_speaker(hass)
    entry = await setup(
        hass,
        announcements={
            "announce_players": ["media_player.alexs_room"],
            "live_activity": ["notify.mobile_app_alexs_iphone"],
        },
    )
    hass.states.async_set(
        SPEAKER,
        "playing",
        {
            **hass.states.get(SPEAKER).attributes,
            "media_content_id": f"https://plex.local:32400/stream.mp3?X-Plex-Token={TOKEN}",
            "entity_picture": f"/api/media_player_proxy/{SPEAKER}?token={TOKEN}",
        },
        context=Context(user_id=USER_ID),
    )
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag)
    for secret in (USER_ID, TOKEN, "alexs_iphone", "alexs_room"):
        assert secret not in text, secret

    state = diag["player"]["state"]
    assert state["context"]["user_id"] == REDACTED
    assert state["attributes"]["entity_picture"] == REDACTED
    # The address stays readable without its query string.
    assert state["attributes"]["media_content_id"] == (
        f"https://plex.local:32400/stream.mp3?{REDACTED}"
    )
    announce = diag["options"]["announcements"]
    assert announce["live_activity"] == REDACTED
    assert announce["announce_players"] == REDACTED
    # Still useful: the speaker and the rules are there.
    assert diag["data"]["media_player"] == SPEAKER
    assert diag["issues"] == []


def test_scrub_urls_at_any_depth() -> None:
    data = {
        "a": "see http://x.local/a?b=c and https://y/z?token=1#frag",
        "b": [{"c": "rtsp://cam/s?auth=2"}],
        "n": 3,
        "plain": "no link? here",
    }
    assert scrub_urls(data) == {
        "a": f"see http://x.local/a?{REDACTED} and https://y/z?{REDACTED}#frag",
        "b": [{"c": f"rtsp://cam/s?{REDACTED}"}],
        "n": 3,
        "plain": "no link? here",
    }
