"""Music filter: songs, artists, albums, apps and words that aren't allowed.

Pure module (no Home Assistant imports) so it can be unit tested alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .media import SEP, base_title, norm, split_artists

KINDS = ["track", "artist", "album", "source", "keyword"]


def clean_list(values: Any) -> list[str]:
    """Strip, drop blanks and duplicates (ignoring case), keep order."""
    if isinstance(values, str):
        values = values.splitlines()
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        text = " ".join(str(value).split())
        if text and norm(text) not in seen:
            seen.add(norm(text))
            result.append(text)
    return result


def track_entry(title: str, artist: str | None) -> str:
    """How a blocked song is written: "Title — Artist"."""
    return f"{title}{SEP}{artist}" if artist else title


def _parse_track(entry: str) -> tuple[str, str | None]:
    for sep in (SEP, " - ", " – "):
        title, found, artist = entry.partition(sep)
        if found and title.strip() and artist.strip():
            return title.strip(), artist.strip()
    return entry.strip(), None


@dataclass
class MusicFilter:
    tracks: list[str] = field(default_factory=list)
    artists: list[str] = field(default_factory=list)
    albums: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._artists = {norm(a) for a in self.artists}
        self._albums = {norm(a) for a in self.albums}
        self._album_bases = {base_title(a) for a in self.albums}
        self._sources = {norm(s) for s in self.sources}
        self._keywords = [
            re.compile(rf"(?<!\w){re.escape(norm(k))}(?!\w)") for k in self.keywords if norm(k)
        ]
        self._tracks: list[tuple[str, str, str | None]] = []
        for entry in self.tracks:
            title, artist = _parse_track(entry)
            # Keep the whole entry as a title too: "Hey Jude - Remastered" is one title.
            self._tracks.append((norm(entry), base_title(title), norm(artist) if artist else None))

    @property
    def empty(self) -> bool:
        return not (self.tracks or self.artists or self.albums or self.sources or self.keywords)

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "track": list(self.tracks),
            "artist": list(self.artists),
            "album": list(self.albums),
            "source": list(self.sources),
            "keyword": list(self.keywords),
        }

    def match(self, media: dict[str, Any] | None) -> tuple[str, str] | None:
        """(kind, rule) of the first rule this media breaks, or None."""
        if not media:
            return None
        title = media.get("title")
        artists = split_artists(media.get("artist"))
        if source := media.get("source"):
            if norm(source) in self._sources:
                return "source", source
        for artist in artists:
            if artist in self._artists:
                return "artist", self._original(self.artists, artist)
        album = media.get("album")
        if album and (norm(album) in self._albums or base_title(album) in self._album_bases):
            return "album", album
        if title:
            whole, base = norm(title), base_title(title)
            for (entry, entry_title, entry_artist), original in zip(self._tracks, self.tracks):
                if entry in (whole, base):
                    return "track", original
                if entry_title in (whole, base) and (entry_artist is None or entry_artist in artists):
                    return "track", original
        text = " ".join(norm(v) for v in (title, album) if v)
        for pattern, original in zip(self._keywords, [k for k in self.keywords if norm(k)]):
            if pattern.search(text):
                return "keyword", original
        return None

    @staticmethod
    def _original(values: list[str], normalized: str) -> str:
        return next((v for v in values if norm(v) == normalized), normalized)


def add_rule(rules: dict[str, list[str]], kind: str, value: str) -> bool:
    """Add a rule to a {kind: [values]} dict. Returns False if it was there."""
    current = clean_list(rules.get(kind, []))
    if norm(value) in {norm(v) for v in current}:
        return False
    rules[kind] = [*current, " ".join(value.split())]
    return True


def remove_rule(rules: dict[str, list[str]], kind: str, value: str) -> bool:
    current = clean_list(rules.get(kind, []))
    kept = [v for v in current if norm(v) != norm(value)]
    rules[kind] = kept
    return len(kept) != len(current)
