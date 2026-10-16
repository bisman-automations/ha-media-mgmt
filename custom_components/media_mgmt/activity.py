"""Activity log: what each speaker played, daily listening totals, and every song played.

Pure module (no Home Assistant imports) so it can be unit tested alone.

Events are small dicts kept in time order:

    {"t": "2026-10-16T19:02:11+00:00", "type": "play", "key": "Song — Artist", "title": "Song", ...}

Daily totals are keyed by local date:

    {"2026-10-16": {"used_seconds": 5400, "schedule_seconds": 1800, "budget_minutes": 90,
                    "extension_minutes": 15, "blocked": 3, "plays": 25,
                    "tracks": {...}, "artists": {...}, "albums": {...}, "sources": {...},
                    "hours": [0, ..., 1800, ...]}}

The library is every song played (the most recent MAX_LIBRARY), keyed like
"Song — Artist", with play counts, time and the IDs needed to play it again.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

# Event types
EV_STATE = "state"  # state, source: the speaker started playing, paused, stopped, turned off
EV_PLAY = "play"  # key, title, artist, album, source: a new song started
EV_BLOCKED = "blocked"  # kind, rule, title, artist, album, source, action, acted
EV_ENFORCEMENT = "enforcement"  # state, reason, quiet_window, schedule
EV_STOPPED = "stopped"  # reason, action: Media Mgmt stopped the music
EV_MODE = "mode"  # mode
EV_FILTER = "filter"  # on: music filter switched
EV_ADULT_MODE = "adult_mode"  # on, minutes
EV_EXTENSION = "extension"  # minutes
EV_BLOCK = "block"  # Stop music now
EV_UNBLOCK = "unblock"
EV_RESET = "reset"
EV_RULE = "rule"  # kind, value, added, by: blocked music changed
EV_SCHEDULE = "schedule"  # id, name, action (started/failed/fading/stopped/stop_idle), detail, by
EV_SLEEP = "sleep"  # action (set/cancelled/fired), minutes, fade, by
EV_VOLUME = "volume"  # from, to, acted: turned down to the cap

EVENT_TYPES = [
    EV_STATE, EV_PLAY, EV_BLOCKED, EV_ENFORCEMENT, EV_STOPPED, EV_MODE, EV_FILTER,
    EV_ADULT_MODE, EV_EXTENSION, EV_BLOCK, EV_UNBLOCK, EV_RESET, EV_RULE, EV_SCHEDULE,
    EV_SLEEP, EV_VOLUME,
]

KEEP_EVENT_DAYS = 90
KEEP_DAILY_DAYS = 400
MAX_EVENTS = 20000
MAX_LIBRARY = 3000
MAX_DAY_TRACKS = 150  # songs kept in a day's totals
LIBRARY_FIELDS = ("title", "artist", "album", "source", "playlist", "content_id", "content_type")
DICT_FIELDS = ("tracks", "artists", "albums", "sources")


def _ts(event: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(event["t"])


def _fold(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _top_dict(values: dict[str, int] | None, limit: int | None = None) -> dict[str, int]:
    items = sorted(((k, int(v)) for k, v in (values or {}).items() if k and v), key=lambda i: i[1], reverse=True)
    return dict(items[:limit] if limit else items)


def _hours(values: Any) -> list[int]:
    hours = [int(v or 0) for v in (values or [])][:24]
    return hours + [0] * (24 - len(hours))


class ActivityLog:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        self.events: list[dict[str, Any]] = list(data.get("events", []))
        self.daily: dict[str, dict[str, Any]] = dict(data.get("daily", {}))
        self.library: dict[str, dict[str, Any]] = dict(data.get("library", {}))

    def as_dict(self) -> dict[str, Any]:
        return {"events": self.events, "daily": self.daily, "library": self.library}

    # ---- writing ---------------------------------------------------------------

    def add(self, when: datetime, event_type: str, **data: Any) -> dict[str, Any]:
        event = {"t": when.isoformat(), "type": event_type, **{k: v for k, v in data.items() if v is not None}}
        if self.events and _ts(self.events[-1]) > when:
            # Keep time order if a clock adjustment slipped in.
            index = len(self.events)
            while index and _ts(self.events[index - 1]) > when:
                index -= 1
            self.events.insert(index, event)
        else:
            self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        return event

    def note_play(self, when: datetime, key: str | None, media: dict[str, Any]) -> None:
        """A song started: count it in the library."""
        if not key:
            return
        item = self.library.get(key)
        if item is None:
            item = self.library[key] = {"plays": 0, "seconds": 0, "first": when.isoformat()}
        for name in LIBRARY_FIELDS:
            if media.get(name):
                item[name] = media[name]
        item["plays"] = item.get("plays", 0) + 1
        item["last"] = when.isoformat()
        if len(self.library) > MAX_LIBRARY:
            oldest = sorted(self.library, key=lambda k: self.library[k].get("last", ""))
            for old in oldest[: len(self.library) - MAX_LIBRARY]:
                del self.library[old]

    def note_seconds(self, key: str | None, seconds: int) -> None:
        if key and (item := self.library.get(key)):
            item["seconds"] = item.get("seconds", 0) + int(seconds)

    def record_day(
        self,
        day: date | str,
        *,
        used_seconds: int,
        budget_minutes: int,
        extension_minutes: int,
        blocked: int = 0,
        plays: int = 0,
        tracks: dict[str, int] | None = None,
        artists: dict[str, int] | None = None,
        albums: dict[str, int] | None = None,
        sources: dict[str, int] | None = None,
        hours: list[int] | None = None,
        schedule_seconds: int = 0,
    ) -> bool:
        """Store a day's totals. Returns True if anything changed."""
        key = day if isinstance(day, str) else day.isoformat()
        record: dict[str, Any] = {
            "used_seconds": int(used_seconds),
            "schedule_seconds": int(schedule_seconds),
            "budget_minutes": int(budget_minutes),
            "extension_minutes": int(extension_minutes),
            "blocked": int(blocked),
            "plays": int(plays),
        }
        for name, values, limit in (
            ("tracks", tracks, MAX_DAY_TRACKS),
            ("artists", artists, None),
            ("albums", albums, None),
            ("sources", sources, None),
        ):
            if values:
                record[name] = _top_dict(values, limit)
        if hours and any(hours):
            record["hours"] = _hours(hours)
        if self.daily.get(key) == record:
            return False
        self.daily[key] = record
        return True

    def prune(self, now: datetime) -> None:
        cutoff = now - timedelta(days=KEEP_EVENT_DAYS)
        first_kept = 0
        while first_kept < len(self.events) and _ts(self.events[first_kept]) < cutoff:
            first_kept += 1
        if first_kept:
            # Keep the last state and song so the first remaining day knows what was on.
            old = self.events[:first_kept]
            carried = [
                e for e in (
                    next((e for e in reversed(old) if e["type"] == EV_STATE), None),
                    next((e for e in reversed(old) if e["type"] == EV_PLAY), None),
                ) if e
            ]
            self.events = sorted(carried, key=_ts) + self.events[first_kept:]
        oldest_day = (now.date() - timedelta(days=KEEP_DAILY_DAYS)).isoformat()
        for key in [k for k in self.daily if k < oldest_day]:
            del self.daily[key]

    # ---- reading ---------------------------------------------------------------

    @property
    def last_state(self) -> str | None:
        return next((e.get("state") for e in reversed(self.events) if e["type"] == EV_STATE), None)

    @property
    def last_play(self) -> dict[str, Any] | None:
        """The last song logged as starting."""
        return next((e for e in reversed(self.events) if e["type"] == EV_PLAY), None)

    @property
    def first_day(self) -> str | None:
        candidates = list(self.daily)
        if self.events:
            candidates.append(_ts(self.events[0]).date().isoformat())
        return min(candidates) if candidates else None

    def events_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return [e for e in self.events if start <= _ts(e) < end]

    def listening_segments(self, start: datetime, end: datetime, now: datetime) -> list[dict[str, Any]]:
        """Stretches of time music played, split by song, clipped to [start, end).

        A stretch still going at `now` is marked live.
        """
        stop = min(end, now)
        segments: list[dict[str, Any]] = []
        playing = False
        song: dict[str, Any] = {}
        since: datetime | None = None

        def close(at: datetime) -> None:
            if not playing or since is None:
                return
            seg_start, seg_end = max(since, start), min(at, stop)
            if seg_end > seg_start:
                segments.append(
                    {
                        "start": seg_start.isoformat(),
                        "end": seg_end.isoformat(),
                        "seconds": int((seg_end - seg_start).total_seconds()),
                        "title": song.get("title"),
                        "artist": song.get("artist"),
                        "album": song.get("album"),
                        "source": song.get("source"),
                        "live": False,
                    }
                )

        for event in self.events:
            when = _ts(event)
            if when >= stop:
                break
            kind = event["type"]
            if kind == EV_STATE:
                now_playing = event.get("state") == "playing"
                if now_playing != playing:
                    close(when)
                    playing, since = now_playing, when if now_playing else None
            elif kind == EV_PLAY:
                close(when)
                song = event
                # A new song is only logged while playing.
                playing, since = True, when

        if playing and since is not None:
            close(stop)
            if segments and stop == now and segments[-1]["end"] == stop.isoformat():
                segments[-1]["live"] = True
        return segments

    def history(self, query: str | None = None, limit: int = 200, sort: str = "last") -> list[dict[str, Any]]:
        """Songs played, most recent (or most played, or most time) first."""
        q = _fold(query)
        items = [
            {"key": key, **item}
            for key, item in self.library.items()
            if not q or any(q in _fold(item.get(f)) for f in ("title", "artist", "album", "source"))
        ]
        sort_key = {"plays": "plays", "seconds": "seconds"}.get(sort, "last")
        items.sort(key=lambda i: (i.get(sort_key) or 0, i.get("last", "")) if sort_key != "last" else i.get("last", ""), reverse=True)
        return items[:limit]

    def artists(self, query: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Artists played, most recent first, with something of theirs to play again."""
        q = _fold(query)
        groups: dict[str, dict[str, Any]] = {}
        latest_with_id: dict[str, str] = {}
        for item in self.library.values():
            artist = item.get("artist")
            if not artist or (q and q not in _fold(artist)):
                continue
            key = _fold(artist)
            group = groups.get(key)
            if group is None:
                group = groups[key] = {"artist": artist, "plays": 0, "seconds": 0, "songs": 0, "last": ""}
            group["plays"] += item.get("plays", 0)
            group["seconds"] += item.get("seconds", 0)
            group["songs"] += 1
            last = item.get("last", "")
            if last > group["last"]:
                group["last"] = last
                group["artist"] = artist
            if item.get("content_id") and last >= latest_with_id.get(key, ""):
                latest_with_id[key] = last
                group["content_id"] = item["content_id"]
                if item.get("content_type"):
                    group["content_type"] = item["content_type"]
                else:
                    group.pop("content_type", None)
        rows = sorted(groups.values(), key=lambda g: g["last"], reverse=True)
        return rows[:limit]

    def daily_series(self, today: date, days: int) -> list[dict[str, Any]]:
        """Totals for the last `days` days, oldest first, zero-filled."""
        series = []
        for offset in range(days - 1, -1, -1):
            key = (today - timedelta(days=offset)).isoformat()
            record = self.daily.get(key) or {}
            series.append(
                {
                    "date": key,
                    "used_seconds": record.get("used_seconds", 0),
                    "schedule_seconds": record.get("schedule_seconds", 0),
                    "budget_minutes": record.get("budget_minutes", 0),
                    "extension_minutes": record.get("extension_minutes", 0),
                    "blocked": record.get("blocked", 0),
                    "plays": record.get("plays", 0),
                    **{name: dict(record.get(name, {})) for name in DICT_FIELDS},
                    "hours": _hours(record.get("hours")),
                    "recorded": bool(record),
                }
            )
        return series


def merge_series(all_series: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Several speakers' daily series added together, day by day.

    There's no one daily limit for the whole house, so the limit is left out.
    """
    if not all_series:
        return []
    merged = []
    for days in zip(*all_series):
        day: dict[str, Any] = {
            "date": days[0]["date"],
            "budget_minutes": 0,
            "extension_minutes": 0,
            "recorded": any(d["recorded"] for d in days),
            "hours": [sum(d["hours"][h] for d in days) for h in range(24)],
        }
        for name in ("used_seconds", "schedule_seconds", "blocked", "plays"):
            day[name] = sum(d.get(name, 0) for d in days)
        for name in DICT_FIELDS:
            totals: dict[str, int] = {}
            for d in days:
                for key, seconds in d.get(name, {}).items():
                    totals[key] = totals.get(key, 0) + seconds
            day[name] = totals
        merged.append(day)
    return merged


def _top(days: list[dict[str, Any]], name: str, limit: int) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    for day in days:
        for key, seconds in day.get(name, {}).items():
            totals[key] = totals.get(key, 0) + seconds
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]


def summarize(series: list[dict[str, Any]], limit: int = 10) -> dict[str, Any]:
    recorded = [d for d in series if d["recorded"]]
    listening = [d["used_seconds"] + d.get("schedule_seconds", 0) for d in recorded]
    total = sum(listening)
    over = [
        d for d in recorded
        if d["budget_minutes"] > 0
        and d["used_seconds"] >= (d["budget_minutes"] + d["extension_minutes"]) * 60
    ]
    return {
        "total_seconds": total,
        "schedule_seconds": sum(d.get("schedule_seconds", 0) for d in recorded),
        "average_seconds": int(total / len(recorded)) if recorded else 0,
        "active_days": len([s for s in listening if s > 0]),
        "days_over_limit": len(over),
        "blocked": sum(d["blocked"] for d in recorded),
        "plays": sum(d["plays"] for d in recorded),
        "hours": [sum(d["hours"][h] for d in recorded) for h in range(24)],
        "top_artists": [{"artist": k, "seconds": v} for k, v in _top(recorded, "artists", limit)],
        "top_tracks": [{"key": k, "seconds": v} for k, v in _top(recorded, "tracks", limit)],
        "top_albums": [{"album": k, "seconds": v} for k, v in _top(recorded, "albums", limit)],
        "top_sources": [{"source": k, "seconds": v} for k, v in _top(recorded, "sources", limit)],
        "recorded_days": len(recorded),
    }
