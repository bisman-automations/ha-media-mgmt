"""Saved artists for the whole home, and playing one on a speaker.

`async_play_request` is the one place every "play this artist" goes through:
the play_artist action, voice and AI assistants, the sidebar app, and the
optional Play artist select and per-artist buttons.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .artists import MAX_ARTISTS, SavedArtist, find_artist
from .const import DOMAIN, SIGNAL_ARTISTS_UPDATED
from .playback import PlayResult
from .storage import ArtistStore
from .targets import find_speaker, target_message

DATA_ARTISTS: HassKey[SavedArtists] = HassKey(f"{DOMAIN}_artists")


class SavedArtists:
    """The home's saved artists."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store = ArtistStore(hass)

    async def async_load(self) -> None:
        await self.store.async_load()

    @property
    def artists(self) -> list[SavedArtist]:
        return self.store.artists

    def get(self, query: str | None) -> SavedArtist | None:
        return find_artist(self.artists, query or "")

    @callback
    def save(self, data: dict[str, Any]) -> SavedArtist:
        """Add an artist, or update one (same ID, or same name)."""
        artist = SavedArtist.from_dict(data)
        existing = next(
            (i for i, a in enumerate(self.artists) if a.id == artist.id or (not data.get("id") and a.matches(artist.name))),
            None,
        )
        if existing is None:
            if len(self.artists) >= MAX_ARTISTS:
                raise ValueError(f"You can save up to {MAX_ARTISTS} artists")
            artist.added = dt_util.utcnow().isoformat()
            self.artists.append(artist)
        else:
            old = self.artists[existing]
            artist.id = old.id
            artist.added = old.added
            self.artists[existing] = artist
        self.artists.sort(key=lambda a: a.name.casefold())
        self._changed()
        return artist

    @callback
    def delete(self, artist_id: str) -> bool:
        before = len(self.artists)
        self.store.artists = [a for a in self.artists if a.id != artist_id]
        if len(self.artists) == before:
            return False
        self._changed()
        return True

    @callback
    def _changed(self) -> None:
        self.store.schedule_save()
        async_dispatcher_send(self.hass, SIGNAL_ARTISTS_UPDATED)


def get_saved(hass: HomeAssistant) -> SavedArtists:
    return hass.data[DATA_ARTISTS]


async def async_load_saved(hass: HomeAssistant) -> SavedArtists:
    if (saved := hass.data.get(DATA_ARTISTS)) is None:
        saved = hass.data[DATA_ARTISTS] = SavedArtists(hass)
        await saved.async_load()
    return saved


async def async_play_request(
    hass: HomeAssistant,
    artist: str,
    *,
    profile_id: str | None = None,
    entity_id: str | None = None,
    speaker: str | None = None,
    area_id: str | None = None,
    media_type: str = "artist",
    uri: str | None = None,
    radio: bool | None = None,
    shuffle: bool | None = None,
    volume: int | None = None,
    enqueue: str = "replace",
    by: str | None = None,
) -> PlayResult:
    """Play an artist (saved or not) on the speaker asked for, if the rules allow it.

    A saved artist (by name, other name or ID) brings its Music Assistant URI,
    radio, shuffle, volume and default speaker; anything given here wins.
    """
    saved = get_saved(hass).get(artist) if media_type == "artist" else None
    target = find_speaker(
        hass,
        profile_id=profile_id,
        entity_id=entity_id,
        speaker=speaker,
        area_id=area_id,
        default_entity=saved.speaker if saved else None,
    )
    name = saved.name if saved else artist.strip()
    if target.manager is None:
        return PlayResult(
            ok=False, name=name, media_type=media_type, reason=target.error, message=target_message(target)
        )
    if saved is not None:
        uri = uri or saved.uri
        radio = saved.radio if radio is None else radio
        shuffle = saved.shuffle if shuffle is None else shuffle
        volume = saved.volume if volume is None else volume
    return await target.manager.async_play_artist(
        name,
        kind=media_type,
        uri=uri,
        radio=bool(radio),
        shuffle=shuffle,
        volume=volume,
        enqueue=enqueue,
        by=by,
    )
