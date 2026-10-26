"""Saved artists: the artists anyone at home can play with one tap or by voice.

Pure module (no Home Assistant imports) so it can be unit tested alone.
Saved artists are home-wide: one list for every speaker, each with an
optional default speaker. Music Assistant finds the exact artist (its URI),
so "play Brahms" never plays a cover band of the same name.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
import re
from typing import Any
import uuid

from .media import norm

MAX_ARTISTS = 200
MAX_ALIASES = 10
MAX_NAME = 120


def provider_of(uri: str | None) -> str | None:
    """The music provider a Music Assistant URI points at.

    "spotify--a1b2://artist/123" -> "spotify", "library://artist/5" -> "library".
    Share links ("https://open.spotify.com/...") give the site's name.
    """
    if not uri:
        return None
    if uri.startswith(("http://", "https://")):
        host = uri.split("://", 1)[1].split("/", 1)[0].lower()
        parts = [p for p in host.split(".") if p not in ("www", "open", "music", "com", "co", "uk", "net", "listen")]
        return parts[0] if parts else host
    scheme, sep, _ = uri.partition("://")
    if not sep:
        scheme = uri.split(":", 1)[0] if ":" in uri else ""
    return scheme.split("--", 1)[0] or None


def clean_aliases(aliases: Any, name: str = "") -> list[str]:
    """Other names for an artist, e.g. "Mozart" for "Wolfgang Amadeus Mozart"."""
    if isinstance(aliases, str):
        aliases = re.split(r"[,\n]", aliases)
    seen = {norm(name)}
    result: list[str] = []
    for alias in aliases or []:
        text = " ".join(str(alias).split())[:MAX_NAME]
        if text and norm(text) not in seen:
            seen.add(norm(text))
            result.append(text)
    return result[:MAX_ALIASES]


def _volume(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return max(0, min(100, int(value)))


@dataclass
class SavedArtist:
    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    uri: str | None = None  # Music Assistant URI, or a share link Sonos can play
    provider: str | None = None
    image: str | None = None
    aliases: list[str] = field(default_factory=list)
    speaker: str | None = None  # default speaker (media player entity ID)
    radio: bool = False  # keep playing similar music once the artist's songs run out
    shuffle: bool = True
    volume: int | None = None  # percent; the speaker's volume cap still applies
    added: str | None = None  # ISO datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SavedArtist:
        name = " ".join(str(data.get("name") or "").split())[:MAX_NAME]
        if not name:
            raise ValueError("An artist needs a name")
        uri = (str(data.get("uri")).strip() or None) if data.get("uri") else None
        artist = cls(
            name=name,
            uri=uri,
            provider=data.get("provider") or provider_of(uri),
            image=data.get("image") or None,
            aliases=clean_aliases(data.get("aliases"), name),
            speaker=data.get("speaker") or None,
            radio=bool(data.get("radio", False)),
            shuffle=bool(data.get("shuffle", True)),
            volume=_volume(data.get("volume")),
            added=data.get("added"),
        )
        if data.get("id"):
            artist.id = str(data["id"])
        return artist

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    def matches(self, query: str) -> bool:
        wanted = norm(query)
        return any(norm(n) == wanted for n in self.names())


def load_artists(raw: Any) -> list[SavedArtist]:
    artists: list[SavedArtist] = []
    for item in raw or []:
        try:
            artists.append(SavedArtist.from_dict(item))
        except (AttributeError, TypeError, ValueError):
            continue  # skip anything stored that isn't an artist
    return artists[:MAX_ARTISTS]


def find_artist(artists: list[SavedArtist], query: str) -> SavedArtist | None:
    """A saved artist by ID, name or alias."""
    if not query:
        return None
    for artist in artists:
        if artist.id == query:
            return artist
    return next((a for a in artists if a.matches(query)), None)


def best_match(results: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """The search result that is this artist: an exact name first, then the top close one.

    Music Assistant sorts results by relevance, so the first result whose name
    is close ("beatles" for "The Beatles", or a small misspelling) is the best
    guess. Nothing close means nothing found, rather than someone else's music.
    """
    items = [r for r in results or [] if isinstance(r, dict) and r.get("uri")]
    if not items:
        return None
    wanted = norm(name)
    exact = [r for r in items if norm(r.get("name")) == wanted]
    if exact:
        # Prefer the user's library copy, then a favourite.
        exact.sort(key=lambda r: (not str(r["uri"]).startswith("library://"), not r.get("favorite")))
        return exact[0]
    return next((r for r in items if _close(norm(r.get("name")), wanted)), None)


def _close(found: str, wanted: str) -> bool:
    if not found or not wanted:
        return False
    if wanted in found or found in wanted:
        return True
    return SequenceMatcher(None, found, wanted).ratio() >= 0.75
