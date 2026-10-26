"""Saved artists and picking the right search result (no Home Assistant needed)."""

from media_mgmt_pure.artists import (
    SavedArtist,
    best_match,
    clean_aliases,
    find_artist,
    load_artists,
    provider_of,
)
import pytest


def test_provider_from_uri() -> None:
    assert provider_of("spotify--a1b2://artist/123") == "spotify"
    assert provider_of("library://artist/5") == "library"
    assert provider_of("apple_music://artist/9") == "apple_music"
    assert provider_of("https://open.spotify.com/artist/abc") == "spotify"
    assert provider_of("https://music.apple.com/us/artist/x/1") == "apple"
    assert provider_of("spotify:artist:abc") == "spotify"
    assert provider_of(None) is None


def test_aliases_are_cleaned() -> None:
    assert clean_aliases(
        "Mozart, mozart ,  W. A. Mozart\nWolfgang Amadeus Mozart",
        "Wolfgang Amadeus Mozart",
    ) == [
        "Mozart",
        "W. A. Mozart",
    ]
    assert clean_aliases(None) == []


def test_saved_artist_round_trip_and_matching() -> None:
    artist = SavedArtist.from_dict(
        {
            "name": "  Wolfgang Amadeus  Mozart ",
            "uri": "spotify--x://artist/1",
            "aliases": "Mozart",
            "volume": 140,
        }
    )
    assert artist.name == "Wolfgang Amadeus Mozart"
    assert artist.provider == "spotify"
    assert artist.volume == 100
    assert artist.shuffle is True and artist.radio is False
    again = SavedArtist.from_dict(artist.as_dict())
    assert again == artist
    assert find_artist([artist], "mozart") is artist
    assert find_artist([artist], artist.id) is artist
    assert find_artist([artist], "Haydn") is None
    with pytest.raises(ValueError):
        SavedArtist.from_dict({"name": " "})


def test_bad_stored_artists_are_skipped() -> None:
    assert [
        a.name
        for a in load_artists([{"name": "Brahms"}, {"name": ""}, "junk", {"nope": 1}])
    ] == ["Brahms"]


def test_best_match_prefers_exact_name_then_library() -> None:
    results = [
        {"name": "Brahms Tribute Band", "uri": "spotify://artist/9"},
        {"name": "Johannes Brahms", "uri": "spotify://artist/1"},
        {"name": "johannes brahms", "uri": "library://artist/3"},
    ]
    assert best_match(results, "Johannes Brahms")["uri"] == "library://artist/3"
    # No exact name: Music Assistant's top result that's close.
    assert best_match(results, "Brahms")["uri"] == "spotify://artist/9"
    assert (
        best_match(results, "Johanes Brahms")["uri"] == "spotify://artist/1"
    )  # misheard
    assert (
        best_match([{"name": "The Beatles", "uri": "x://1"}], "beatles")["uri"]
        == "x://1"
    )
    # Nothing close: not found, rather than someone else.
    assert best_match(results, "Raffi") is None
    assert best_match([], "Brahms") is None
    assert best_match([{"name": "No URI"}], "No URI") is None
