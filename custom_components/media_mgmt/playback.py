"""Playing an artist, album, song or playlist on a speaker.

One path for everything that starts music: the play_artist action, voice
and AI assistants, the sidebar app, per-artist buttons and schedules. It
picks the best way the speaker allows:

- Music Assistant (the speaker itself, or the Music Assistant player for
  it): find the exact artist with Music Assistant's search, then play it.
- Sonos without Music Assistant: a Sonos favourite with that name, or a
  share link (open.spotify.com/..., music.apple.com/...).
- HomePod / Apple TV without Music Assistant: can't search, so say how to
  fix it (add the HomePod to Music Assistant's AirPlay provider).
- Anything else: a media ID, a source with that name, or the most played
  song from this speaker's history.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .artists import best_match, provider_of
from .const import MUSIC_ASSISTANT_DOMAIN
from .ma_link import ma_config_entry
from .media import norm

if TYPE_CHECKING:
    from .manager import MediaManager

_LOGGER = logging.getLogger(__name__)

MEDIA_KINDS = ("artist", "album", "track", "playlist")

# How the music was started.
VIA_MUSIC_ASSISTANT = "music_assistant"
VIA_FAVORITE = "favorite"  # a Sonos favourite or other source on the speaker
VIA_SHARE_LINK = "share_link"
VIA_MEDIA_ID = "media_id"
VIA_HISTORY = "history"

# Why music wasn't played.
REFUSED_BLOCKED = "blocked"
REFUSED_LIMIT = "limit"
REFUSED_NOT_FOUND = "not_found"
REFUSED_UNSUPPORTED = "unsupported"
REFUSED_FAILED = "failed"
REFUSED_UNAVAILABLE = "unavailable"


@dataclass
class PlayResult:
    """What happened when asked to play something. Also the play_artist action's response."""

    ok: bool
    speaker: str | None = None
    entity_id: str | None = None  # the media player that was told to play
    name: str | None = None  # the artist (or album, song, playlist) that played
    media_type: str = "artist"
    uri: str | None = None
    provider: str | None = None
    method: str | None = None  # VIA_*
    radio: bool = False
    reason: str | None = None  # REFUSED_* when ok is False
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_share_link(value: str | None) -> bool:
    return bool(value) and value.startswith(("http://", "https://"))


def is_uri(value: str | None) -> bool:
    """A media ID or link rather than a name."""
    if not value:
        return False
    return (
        is_share_link(value)
        or value.startswith(("media-source://", "library://", "spotify:", "apple_music:"))
        or ("://" in value and " " not in value)
        or (":" in value and " " not in value)
    )


async def ma_search(
    hass: HomeAssistant, config_entry_id: str | None, name: str, media_type: str, *, limit: int = 5
) -> list[dict[str, Any]] | None:
    """Music Assistant search results, or None when search isn't available."""
    if not config_entry_id or not hass.services.has_service(MUSIC_ASSISTANT_DOMAIN, "search"):
        return None
    try:
        response = await hass.services.async_call(
            MUSIC_ASSISTANT_DOMAIN,
            "search",
            {"config_entry_id": config_entry_id, "name": name, "media_type": [media_type], "limit": limit},
            blocking=True,
            return_response=True,
        )
    except (HomeAssistantError, ValueError) as err:
        _LOGGER.warning("Media Mgmt: Music Assistant search for %s %r failed: %s", media_type, name, err)
        return None
    key = "radio" if media_type == "radio" else f"{media_type}s"
    items = (response or {}).get(key) or []
    return [i for i in items if isinstance(i, dict)]


def result_item(item: dict[str, Any]) -> dict[str, Any]:
    """A search result trimmed to what the sidebar app shows."""
    uri = item.get("uri")
    artists = item.get("artists") or []
    return {
        "name": item.get("name"),
        "uri": uri,
        "media_type": item.get("media_type"),
        "provider": provider_of(uri),
        "image": item.get("image"),
        "favorite": bool(item.get("favorite")),
        "artist": ", ".join(a.get("name", "") for a in artists if isinstance(a, dict)) or None,
    }


def _favourite(sources: list[str], name: str) -> str | None:
    """A Sonos favourite (or other source) named after the artist: exact, else the only one containing it."""
    wanted = norm(name)
    if not wanted:
        return None
    exact = [s for s in sources if norm(s) == wanted]
    if exact:
        return exact[0]
    partial = [s for s in sources if wanted in norm(s)]
    return partial[0] if len(partial) == 1 else None


async def async_play_media_item(
    manager: MediaManager,
    kind: str,
    name: str,
    *,
    uri: str | None = None,
    radio: bool = False,
    enqueue: str = "replace",
) -> PlayResult:
    """Play an artist, album, song or playlist the best way this speaker allows.

    `name` may itself be a media ID or link. Doesn't check the rules; the
    caller does (schedules play through limits on purpose).
    """
    player = manager.player
    if uri is None and is_uri(name):
        uri = name
    result = PlayResult(ok=False, speaker=manager.name, name=name, media_type=kind, uri=uri, radio=radio)
    result.provider = provider_of(uri)

    # Music Assistant: on the speaker itself, or its Music Assistant player.
    if (ma_entity := player.ma_entity_id) is not None:
        result.entity_id = ma_entity
        result.method = VIA_MUSIC_ASSISTANT
        media_id: str = uri or name
        if uri is None:
            results = await ma_search(manager.hass, ma_config_entry(manager.hass, manager.ma_link), name, kind)
            if results is not None:
                best = best_match(results, name)
                if best is None:
                    result.reason = REFUSED_NOT_FOUND
                    result.message = f"Music Assistant couldn't find the {kind} {name}"
                    return result
                media_id = result.uri = best["uri"]
                result.name = best.get("name") or name
                result.provider = provider_of(media_id)
        if await player.async_music_assistant(media_id, kind, radio=radio, enqueue=enqueue):
            result.ok = True
            result.message = f"Playing {result.name} on {manager.name}"
        else:
            result.reason = REFUSED_FAILED
            result.message = f"Music Assistant couldn't play {result.name} on {manager.name}"
        return result

    result.entity_id = player.entity_id
    platform = player.platform

    if platform == "apple_tv" and not is_share_link(uri):
        result.reason = REFUSED_UNSUPPORTED
        result.message = (
            f"{manager.name} is a HomePod or Apple TV, which can't search for music by itself. "
            "Add it to Music Assistant (AirPlay provider) and Media Mgmt will play through it."
        )
        return result

    # A Sonos favourite (or another source) with the same name.
    if not uri and (source := _favourite(player.source_list, name)):
        result.method = VIA_FAVORITE
        result.ok = await player.async_select_source(source)
        result.message = f"Playing the favourite {source} on {manager.name}" if result.ok else (
            f"{manager.name} couldn't play the favourite {source}"
        )
        result.reason = None if result.ok else REFUSED_FAILED
        return result

    if uri:
        share = is_share_link(uri)
        result.method = VIA_SHARE_LINK if share else VIA_MEDIA_ID
        # Sonos plays share links as "music"; other speakers get the kind.
        content_type = "music" if share or platform == "sonos" else kind
        result.ok = await player.async_play_media(uri, content_type, enqueue=enqueue)
        result.message = f"Playing {name} on {manager.name}" if result.ok else f"{manager.name} couldn't play {uri}"
        result.reason = None if result.ok else REFUSED_FAILED
        return result

    if platform != "apple_tv" and (item := manager.library_match(kind, name)):
        content_id, content_type = item["content_id"], item.get("content_type") or "music"
        result.method = VIA_HISTORY
        result.uri = content_id
        result.ok = await player.async_play_media(content_id, content_type, enqueue=enqueue)
        result.message = (
            f"Playing {item.get('title')} by {item.get('artist')} on {manager.name}, from what played before"
            if result.ok
            else f"{manager.name} couldn't play {item.get('title')}"
        )
        result.reason = None if result.ok else REFUSED_FAILED
        return result

    result.reason = REFUSED_UNSUPPORTED
    hint = (
        "save a Sonos favourite with that name, add the artist with a share link, "
        if platform == "sonos"
        else ""
    )
    result.message = (
        f"{manager.name} can't search for the {kind} {name}. To fix it, {hint}link the speaker to "
        "Music Assistant, or play a playlist, a favourite (source) or a media ID instead."
    )
    return result
