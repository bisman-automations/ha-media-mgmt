"""What's playing on a speaker: the song, artist, album and app.

Pure module (no Home Assistant imports) so it can be unit tested alone.
Works from a media player's standard attributes, so it covers Sonos,
HomePod/AirPlay, Google Cast, Music Assistant, Spotify, Alexa and others.
"""

from __future__ import annotations

import re
from typing import Any

PLAYING = "playing"
PAUSED = "paused"
SEP = " — "  # between a song and its artist, e.g. "Clair de Lune — Debussy"

# "A, B & C feat. D" -> A, B, C, D
_ARTIST_SPLIT = re.compile(
    r"\s*(?:,|&|;|/|\bfeat\.|\bfeat\b|\bft\.|\bft\b|\bfeaturing\b)\s*", re.IGNORECASE
)
# Version suffixes that shouldn't stop a song from matching: "(Remastered 2011)", "- Live"
_SUFFIX = re.compile(r"\s*(?:\([^)]*\)|\[[^\]]*\]|\s-\s.*)$")


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def norm(value: str | None) -> str:
    """Compare names without case, curly quotes or extra spaces."""
    return " ".join((value or "").casefold().replace("’", "'").split())


def base_title(title: str | None) -> str:
    """A title without its version suffix: "Yesterday - Remastered 2009" -> "yesterday"."""
    text = norm(title)
    while True:
        stripped = _SUFFIX.sub("", text).strip()
        if stripped == text or not stripped:
            return text
        text = stripped


def split_artists(artist: str | None) -> list[str]:
    """Every artist credited, plus the credit as written."""
    if not artist:
        return []
    parts = [norm(p) for p in _ARTIST_SPLIT.split(artist) if p and p.strip()]
    return list(dict.fromkeys([norm(artist), *parts]))


def media_from(state: str | None, attributes: dict[str, Any]) -> dict[str, Any] | None:
    """What's on the speaker, or None when nothing is playing or paused."""
    if state not in (PLAYING, PAUSED):
        return None
    title = _clean(attributes.get("media_title"))
    if not title:
        return None
    media: dict[str, Any] = {
        "title": title,
        "artist": _clean(attributes.get("media_artist"))
        or _clean(attributes.get("media_album_artist")),
        "album": _clean(attributes.get("media_album_name")),
        "source": _clean(attributes.get("app_name"))
        or _clean(attributes.get("source")),
        "playlist": _clean(attributes.get("media_playlist")),
        "content_id": _clean(attributes.get("media_content_id")),
        "content_type": _clean(attributes.get("media_content_type")),
    }
    return {k: v for k, v in media.items() if v is not None}


def track_key(media: dict[str, Any] | None) -> str | None:
    """How a song is filed in history: "Title — Artist" (or just the title)."""
    if not media or not media.get("title"):
        return None
    artist = media.get("artist")
    return f"{media['title']}{SEP}{artist}" if artist else media["title"]


def split_key(key: str) -> tuple[str, str | None]:
    """The reverse of track_key."""
    title, sep, artist = key.partition(SEP)
    return (title, artist) if sep else (key, None)


def media_id(media: dict[str, Any] | None) -> tuple | None:
    """Identity of one play, to tell when the song changes."""
    if not media:
        return None
    return (
        media.get("title"),
        media.get("artist"),
        media.get("album"),
        media.get("content_id"),
    )


def describe(media: dict[str, Any] | None) -> str | None:
    """One line, e.g. "Clair de Lune by Debussy"."""
    if not media:
        return None
    title = media.get("title") or ""
    return f"{title} by {media['artist']}" if media.get("artist") else title
