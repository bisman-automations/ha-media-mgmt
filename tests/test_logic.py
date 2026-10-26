from datetime import UTC, date, datetime, time, timedelta, timezone

from media_mgmt_pure.activity import (
    EV_PLAY,
    EV_STATE,
    ActivityLog,
    merge_series,
    summarize,
)
from media_mgmt_pure.filters import MusicFilter, add_rule, clean_list, remove_rule
from media_mgmt_pure.media import (
    base_title,
    describe,
    media_from,
    split_artists,
    split_key,
    track_key,
)
from media_mgmt_pure.quiet import parse_windows
from media_mgmt_pure.schedules import Schedule, load_schedules
from media_mgmt_pure.state import decide
import pytest

TZ = timezone(timedelta(hours=-5))


# ---- media ------------------------------------------------------------------


def test_media_from_attributes() -> None:
    media = media_from(
        "playing",
        {
            "media_title": "Clair de Lune",
            "media_artist": "Debussy",
            "app_name": "Spotify",
        },
    )
    assert media == {"title": "Clair de Lune", "artist": "Debussy", "source": "Spotify"}
    assert media_from("idle", {"media_title": "x"}) is None
    assert media_from("playing", {}) is None
    assert track_key(media) == "Clair de Lune — Debussy"
    assert split_key("Clair de Lune — Debussy") == ("Clair de Lune", "Debussy")
    assert describe(media) == "Clair de Lune by Debussy"


def test_split_artists_and_versions() -> None:
    assert split_artists("Pinkfong & Hogi feat. Baby Shark") == [
        "pinkfong & hogi feat. baby shark",
        "pinkfong",
        "hogi",
        "baby shark",
    ]
    assert base_title("Yesterday - Remastered 2009") == "yesterday"
    assert base_title('Let It Go (From "Frozen") [Live]') == "let it go"


# ---- filter -----------------------------------------------------------------


def song(title, artist=None, album=None, source=None):
    return {
        k: v
        for k, v in {
            "title": title,
            "artist": artist,
            "album": album,
            "source": source,
        }.items()
        if v
    }


def test_filter_matches() -> None:
    f = MusicFilter(
        tracks=["Baby Shark — Pinkfong", "Let It Go"],
        artists=["Cocomelon"],
        albums=["Kidz Bop 40"],
        sources=["YouTube Music"],
        keywords=["explicit"],
    )
    assert f.match(song("Baby Shark", "Pinkfong")) == ("track", "Baby Shark — Pinkfong")
    assert f.match(song("Baby Shark", "Someone Else")) is None
    assert f.match(song("Let It Go - Live", "Idina Menzel")) == ("track", "Let It Go")
    assert f.match(song("Wheels", "Cocomelon & Friends")) == ("artist", "Cocomelon")
    assert f.match(song("Any", "Me", album="Kidz Bop 40 (Deluxe)")) == (
        "album",
        "Kidz Bop 40 (Deluxe)",
    )
    assert f.match(song("Any", "Me", source="youtube music")) == (
        "source",
        "youtube music",
    )
    assert f.match(song("Song (Explicit)", "Me")) == ("keyword", "explicit")
    assert f.match(song("Inexplicitly fine", "Me")) is None
    assert f.match(song("Clair de Lune", "Debussy")) is None


def test_filter_track_with_hyphen() -> None:
    f = MusicFilter(tracks=["Baby Shark - Pinkfong"])
    assert f.match(song("Baby Shark", "Pinkfong"))


def test_rule_editing() -> None:
    rules = {"artist": ["Cocomelon"]}
    assert add_rule(rules, "artist", "  Pinkfong ")
    assert not add_rule(rules, "artist", "cocomelon")
    assert rules["artist"] == ["Cocomelon", "Pinkfong"]
    assert remove_rule(rules, "artist", "COCOMELON")
    assert rules["artist"] == ["Pinkfong"]
    assert clean_list("a\n\nA\n b ") == ["a", "b"]


# ---- decisions --------------------------------------------------------------


def base(**over):
    args = dict(
        now=time(12),
        mode="enforced",
        adult_mode=False,
        force_block=False,
        budget_minutes=60,
        extension_minutes=0,
        used_seconds=0,
        warn_minutes=5,
        quiet_windows=[],
    )
    args.update(over)
    return decide(**args)


def test_decide() -> None:
    assert base().state == "ok"
    assert base(used_seconds=56 * 60).state == "warning"
    assert base(used_seconds=3600).reason == "budget"
    assert base(used_seconds=3600, extension_minutes=4).state == "warning"
    assert base(used_seconds=3600, extension_minutes=10).state == "ok"
    bedtime = parse_windows("20:00-07:00 Bedtime")
    assert base(now=time(21), quiet_windows=bedtime).quiet_window == "Bedtime"
    # A schedule plays through the quiet window and limit, but not a parent's block.
    assert (
        base(
            now=time(21),
            quiet_windows=bedtime,
            used_seconds=9999,
            schedule="Bedtime music",
        ).state
        == "schedule"
    )
    assert base(force_block=True, schedule="Bedtime music").reason == "manual"
    assert base(adult_mode=True, force_block=True).state == "adult_mode"
    assert base(mode="paused", force_block=True).state == "paused"


# ---- schedules --------------------------------------------------------------


def test_schedule_validation() -> None:
    s = Schedule.from_dict(
        {
            "name": " Bed ",
            "days": [6, 0, 9],
            "start": "7:45",
            "stop": None,
            "play_kind": "artist",
            "play_value": "Brahms",
            "volume": 140,
        }
    )
    assert (s.name, s.days, s.start, s.stop, s.volume) == (
        "Bed",
        [0, 6],
        "07:45",
        None,
        100,
    )
    with pytest.raises(ValueError):
        Schedule.from_dict({"days": [0]})
    with pytest.raises(ValueError):
        Schedule.from_dict({"days": [], "stop": "20:00"})
    with pytest.raises(ValueError):
        Schedule.from_dict(
            {"days": [0], "start": "20:00", "play_kind": "artist", "play_value": ""}
        )
    assert (
        Schedule.from_dict(
            {"days": [0], "start": "20:00", "play_kind": "resume"}
        ).play_kind
        == "resume"
    )
    assert (
        load_schedules([{"days": [0]}, {"days": [1], "stop": "21:00"}])[0].stop
        == "21:00"
    )


def test_occurrences_cross_midnight() -> None:
    s = Schedule.from_dict(
        {
            "days": [4],
            "start": "23:00",
            "stop": "01:00",
            "play_kind": "resume",
            "fade_minutes": 30,
        }
    )
    fri = datetime(2026, 10, 16, 23, 30, tzinfo=TZ)  # a Friday
    sat = datetime(2026, 10, 17, 0, 45, tzinfo=TZ)
    (occ,) = [o for o in s.occurrences(sat) if o.start]
    assert occ.key == "2026-10-16"
    assert occ.contains(fri) and occ.contains(sat)
    assert occ.fade_due(sat) and not occ.fade_due(fri)
    assert occ.stop_due(datetime(2026, 10, 17, 1, 5, tzinfo=TZ))
    assert not occ.stop_due(datetime(2026, 10, 17, 1, 15, tzinfo=TZ))
    assert s.next_run(fri) == datetime(2026, 10, 23, 23, 0, tzinfo=TZ)


def test_start_grace() -> None:
    s = Schedule.from_dict(
        {
            "days": [0, 1, 2, 3, 4, 5, 6],
            "start": "19:45",
            "stop": "20:30",
            "play_kind": "resume",
        }
    )
    now = datetime(2026, 10, 16, 19, 50, tzinfo=TZ)
    assert any(o.start_due(now) for o in s.occurrences(now))
    late = datetime(2026, 10, 16, 20, 0, tzinfo=TZ)
    assert not any(o.start_due(late) for o in s.occurrences(late))


# ---- activity ---------------------------------------------------------------


def t(hour, minute=0):
    return datetime(2026, 10, 16, hour, minute, tzinfo=UTC)


def test_segments_and_library() -> None:
    log = ActivityLog()
    log.add(t(19), EV_STATE, state="playing")
    log.add(t(19), EV_PLAY, key="A — X", title="A", artist="X")
    log.note_play(t(19), "A — X", {"title": "A", "artist": "X", "content_id": "id:a"})
    log.add(t(19, 5), EV_PLAY, key="B — Y", title="B", artist="Y")
    log.note_play(t(19, 5), "B — Y", {"title": "B", "artist": "Y"})
    log.note_play(t(19, 9), "A — X", {"title": "A", "artist": "X"})
    log.add(t(19, 10), EV_STATE, state="paused")
    segs = log.listening_segments(t(0), t(23, 59), t(23))
    assert [(s["artist"], s["seconds"]) for s in segs] == [("X", 300), ("Y", 300)]
    log.note_seconds("A — X", 120)
    hist = log.history(sort="plays")
    assert (
        hist[0]["key"] == "A — X"
        and hist[0]["plays"] == 2
        and hist[0]["seconds"] == 120
    )
    assert log.history("y")[0]["artist"] == "Y"
    assert log.artists()[0] == {
        "artist": "X",
        "plays": 2,
        "seconds": 120,
        "songs": 1,
        "last": t(19, 9).isoformat(),
        "content_id": "id:a",
    }


def test_daily_summary() -> None:
    log = ActivityLog()
    hours = [0] * 24
    hours[19] = 1800
    log.record_day(
        "2026-10-15",
        used_seconds=1800,
        budget_minutes=30,
        extension_minutes=0,
        plays=8,
        artists={"X": 1200, "Y": 600},
        tracks={"A — X": 1200},
        hours=hours,
        schedule_seconds=600,
    )
    series = log.daily_series(date(2026, 10, 16), 7)
    s = summarize(series)
    assert s["total_seconds"] == 2400 and s["days_over_limit"] == 1 and s["plays"] == 8
    assert s["top_artists"][0] == {"artist": "X", "seconds": 1200}
    assert s["hours"][19] == 1800 and s["recorded_days"] == 1
    merged = merge_series([series, series])
    assert merged[-2]["artists"]["X"] == 2400 and merged[-2]["plays"] == 16


def test_schedule_volume_limit():
    from media_mgmt_pure.schedules import Schedule

    s = Schedule.from_dict(
        {
            "days": [0],
            "start": "19:30",
            "stop": "20:30",
            "play_value": "Brahms",
            "volume": 50,
            "volume_limit": 30,
        }
    )
    assert s.volume_limit == 30
    assert s.volume == 30  # never starts above its own limit
    assert s.as_dict()["volume_limit"] == 30
    # Only a schedule with both times is ever "playing", so a limit needs both.
    assert (
        Schedule.from_dict(
            {"days": [0], "start": "19:30", "play_value": "Brahms", "volume_limit": 30}
        ).volume_limit
        is None
    )
    assert (
        Schedule.from_dict(
            {"days": [0], "stop": "20:30", "volume_limit": 30}
        ).volume_limit
        is None
    )
    assert (
        Schedule.from_dict(
            {
                "days": [0],
                "start": "19:30",
                "stop": "20:30",
                "play_value": "x",
                "volume_limit": 1,
            }
        ).volume_limit
        == 5
    )
    # Schedules saved before 0.3.0 have no limit.
    assert (
        Schedule.from_dict(
            {"days": [0], "start": "19:30", "stop": "20:30", "play_value": "x"}
        ).volume_limit
        is None
    )


def test_volume_limit_only_schedule():
    from media_mgmt_pure.schedules import Schedule
    import pytest

    s = Schedule.from_dict(
        {
            "days": [0],
            "start": "06:00",
            "stop": "08:00",
            "play_kind": "none",
            "volume_limit": 20,
            "volume": 50,
            "lift_limits": True,
            "fade_minutes": 10,
        }
    )
    assert s.limit_only and s.volume_limit == 20
    assert s.volume is None and s.fade_minutes == 0 and s.play_value == ""
    assert s.lift_limits is False  # plays nothing, so it lifts nothing
    with pytest.raises(ValueError):
        Schedule.from_dict(
            {"days": [0], "start": "06:00", "play_kind": "none", "volume_limit": 20}
        )
    with pytest.raises(ValueError):
        Schedule.from_dict(
            {"days": [0], "start": "06:00", "stop": "08:00", "play_kind": "none"}
        )
