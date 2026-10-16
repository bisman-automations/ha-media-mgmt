"""MediaManager: one per profile (speaker). Tracks listening and enforces rules."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from . import activity as act
from .announce import Announcer, stopping_message, warning_message
from .const import (
    ACT_COOLDOWN,
    ACT_DELAY,
    ACTION_PAUSE,
    ANNOUNCE_GRACE,
    BLOCK_KINDS,
    CONF_ADULT_MODE_DURATION,
    CONF_ANNOUNCE_ON_PLAYER,
    CONF_ANNOUNCE_PLAYERS,
    CONF_ANNOUNCE_TTS,
    CONF_BLOCKED_ALBUMS,
    CONF_BLOCKED_ARTISTS,
    CONF_BLOCKED_KEYWORDS,
    CONF_BLOCKED_SOURCES,
    CONF_BLOCKED_TRACKS,
    CONF_DAILY_BUDGET,
    CONF_FILTER_ACTION,
    CONF_LIMIT_ACTION,
    CONF_MAX_VOLUME,
    CONF_MEDIA_PLAYER,
    CONF_QUIET_WINDOWS,
    CONF_WARN_MINUTES,
    DEFAULT_ADULT_MODE_DURATION,
    DEFAULT_DAILY_BUDGET,
    DEFAULT_FILTER_ACTION,
    DEFAULT_LIMIT_ACTION,
    DEFAULT_MAX_VOLUME,
    DEFAULT_WARN_MINUTES,
    EVENT_ENFORCEMENT_CHANGED,
    EVENT_MEDIA_BLOCKED,
    EVENT_SCHEDULE,
    EVENT_WARNING,
    FADE_STEP,
    MAX_ACT_RETRY,
    SECTION_FILTER,
    SIGNAL_ANY_UPDATED,
    SIGNAL_UPDATED,
    TICK_INTERVAL,
    VOLUME_COOLDOWN,
)
from .filters import MusicFilter, add_rule, clean_list, remove_rule
from .media import describe, media_id, norm, track_key
from .player import Player
from .quiet import QuietWindow, parse_windows
from .schedules import (
    PLAY_CONTENT,
    PLAY_RESUME,
    PLAY_SOURCE,
    Schedule,
)
from .state import (
    MODE_ENFORCED,
    MODES,
    STATE_ENFORCING,
    STATE_OK,
    STATE_SCHEDULE,
    STATE_WARNING,
    Decision,
    decide,
)
from .storage import ActivityStore, ProfileState, ProfileStore, ScheduleStore

_LOGGER = logging.getLogger(__name__)

# A single gap longer than this means HA was down or the clock jumped;
# don't count it as listening.
RESUME_PLAY_WITHIN = timedelta(hours=1)
MAX_TICK_GAP = timedelta(minutes=5)
MAX_FILTER_TRIES = 3
VOLUME_LOG_EVERY = timedelta(minutes=2)
FADE_FLOOR = 0.02  # don't fade all the way to silence before stopping


def flatten_options(options: dict[str, Any]) -> dict[str, Any]:
    """Options are grouped into form sections; read them as one dict."""
    flat: dict[str, Any] = {}
    for key, value in options.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def _looks_like_uri(value: str) -> bool:
    return value.startswith(("http://", "https://", "media-source://")) or (
        ":" in value and " " not in value
    ) or value.startswith(("library://", "spotify:", "apple_music:"))


class MediaManager:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.player = Player(hass, entry.data[CONF_MEDIA_PLAYER])
        self.store = ProfileStore(hass, entry.entry_id)
        self.activity_store = ActivityStore(hass, entry.entry_id)
        self.schedule_store = ScheduleStore(hass, entry.entry_id)
        self.decision = Decision(STATE_OK)
        self.options: dict[str, Any] = {}
        self.filter = MusicFilter()
        self.quiet_windows: list[QuietWindow] = []
        self.announcer: Announcer | None = None
        self.apply_options(dict(entry.options), start=False)

        self._unsubs: list[CALLBACK_TYPE] = []
        self._last_tick: datetime | None = None
        # What was playing at the last count, credited the time since then.
        self._counting: dict[str, Any] | None = None
        self._logged_state: str | None = None
        self._logged_play: tuple | None = None

        # Stopping music when it isn't allowed (limit, quiet window, Block now)
        self._unsub_stop: CALLBACK_TYPE | None = None
        self._stop_attempts = 0
        self._stop_announced = False
        self._last_stop: datetime | None = None

        # Blocked music
        self._filter_key: tuple | None = None
        self._filter_tries = 0
        self._unsub_filter: CALLBACK_TYPE | None = None

        # Volume cap
        self._last_volume_fix: datetime | None = None
        self._last_volume_log: datetime | None = None

        # Fading out before a sleep timer or schedule stops the music
        self._fade: dict[str, Any] | None = None
        self._unsub_fade: CALLBACK_TYPE | None = None

    # ---- options -----------------------------------------------------------------

    @callback
    def apply_options(self, options: dict[str, Any], *, start: bool = True) -> None:
        """Use new settings without reloading the profile."""
        self.options = flatten_options(options)
        o = self.options
        self.filter = MusicFilter(
            tracks=clean_list(o.get(CONF_BLOCKED_TRACKS)),
            artists=clean_list(o.get(CONF_BLOCKED_ARTISTS)),
            albums=clean_list(o.get(CONF_BLOCKED_ALBUMS)),
            sources=clean_list(o.get(CONF_BLOCKED_SOURCES)),
            keywords=clean_list(o.get(CONF_BLOCKED_KEYWORDS)),
        )
        try:
            self.quiet_windows = parse_windows(o.get(CONF_QUIET_WINDOWS, ""))
        except ValueError as err:
            _LOGGER.error("Media Mgmt %s: ignoring bad quiet windows: %s", self.entry.title, err)
            self.quiet_windows = []
        self.announcer = Announcer(
            self.hass,
            tts_entity=o.get(CONF_ANNOUNCE_TTS),
            player=self.player.entity_id,
            on_player=bool(o.get(CONF_ANNOUNCE_ON_PLAYER)),
            players=list(o.get(CONF_ANNOUNCE_PLAYERS) or []),
            player_can_announce=lambda: self.player.supports(F.MEDIA_ANNOUNCE),
        )
        if start:
            self._filter_key = None  # re-check what's playing against the new rules
            self._recompute()
            self._evaluate()
            self.notify()

    # ---- properties --------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.entry.title

    @property
    def entity_id(self) -> str:
        return self.player.entity_id

    @property
    def state(self) -> ProfileState:
        return self.store.state

    @property
    def activity(self) -> act.ActivityLog:
        return self.activity_store.log

    @property
    def schedules(self) -> list[Schedule]:
        return self.schedule_store.schedules

    @property
    def daily_budget(self) -> int:
        return int(self.options.get(CONF_DAILY_BUDGET, DEFAULT_DAILY_BUDGET))

    @property
    def warn_minutes(self) -> int:
        return int(self.options.get(CONF_WARN_MINUTES, DEFAULT_WARN_MINUTES))

    @property
    def adult_mode_duration(self) -> int:
        return int(self.options.get(CONF_ADULT_MODE_DURATION, DEFAULT_ADULT_MODE_DURATION))

    @property
    def max_volume(self) -> int:
        return int(self.options.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME))

    @property
    def limit_action(self) -> str:
        return self.options.get(CONF_LIMIT_ACTION) or DEFAULT_LIMIT_ACTION

    @property
    def filter_action(self) -> str:
        return self.options.get(CONF_FILTER_ACTION) or DEFAULT_FILTER_ACTION

    @property
    def adult_mode_active(self) -> bool:
        until = self.state.adult_mode_until_dt
        return until is not None and until > dt_util.utcnow()

    def _enforcing(self) -> bool:
        """Act on rules (enforced) vs. only report them (monitor only)."""
        return self.state.mode == MODE_ENFORCED

    # ---- lifecycle ---------------------------------------------------------------

    async def async_start(self) -> None:
        await self.store.async_load()
        await self.activity_store.async_load()
        await self.schedule_store.async_load()
        self.activity.prune(dt_util.utcnow())
        self._logged_state = self.activity.last_state
        self._logged_play = None
        self._rollover_if_needed(dt_util.now())

        self.player.async_start(self._on_player_update)
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._on_tick, timedelta(seconds=TICK_INTERVAL),
                name=f"media_mgmt tick {self.name}",
            )
        )
        self._last_tick = dt_util.utcnow()
        self._resume_logged_play()
        self._snapshot()
        self._log_state()
        self._log_play()
        self._recompute(fire_events=False)
        self._check_schedules()
        self._evaluate()
        self._record_today()

    async def async_stop(self) -> None:
        self._count_usage()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self.player.async_stop()
        for name in ("_unsub_stop", "_unsub_filter", "_unsub_fade"):
            if unsub := getattr(self, name):
                unsub()
                setattr(self, name, None)
        self._record_today()
        await self.store.async_save()
        await self.activity_store.async_save()
        await self.schedule_store.async_save()

    # ---- updates -----------------------------------------------------------------

    @callback
    def _on_player_update(self) -> None:
        self._count_usage()  # credit the time until now to what was playing
        self._snapshot()
        self._log_state()
        self._log_play()
        self._recompute()
        self._evaluate()
        self.notify()

    @callback
    def _on_tick(self, _now: datetime) -> None:
        self._count_usage()
        self._snapshot()
        self._recompute()
        self._check_schedules()
        self._evaluate()
        self.notify()

    # ---- counting ----------------------------------------------------------------

    @callback
    def _snapshot(self) -> None:
        media = self.player.media if self.player.is_playing else None
        self._counting = (
            {
                "key": track_key(media),
                "artist": media.get("artist"),
                "album": media.get("album"),
                "source": media.get("source"),
            }
            if media
            else ({"key": None} if self.player.is_playing else None)
        )

    def _rollover_if_needed(self, local_now: datetime) -> None:
        today = local_now.date()
        if self.state.day != today.isoformat():
            self._record_today()  # close out the finished day
            self.state.reset_day(today)
            self.store.schedule_save()

    @callback
    def _count_usage(self) -> None:
        now = dt_util.utcnow()
        last, self._last_tick = self._last_tick, now
        local_now = dt_util.as_local(now)
        playing = self._counting
        if last is not None and playing is not None:
            elapsed = now - last
            if timedelta(0) < elapsed <= MAX_TICK_GAP:
                midnight = dt_util.start_of_local_day(local_now)
                local_last = dt_util.as_local(last)
                if local_last < midnight:
                    self._credit(int((midnight - local_last).total_seconds()), playing, local_last.hour)
                    self._rollover_if_needed(local_now)
                    elapsed = local_now - midnight
                self._credit(int(elapsed.total_seconds()), playing, local_now.hour)
                self.store.schedule_save()
        self._rollover_if_needed(local_now)
        if self.state.adult_mode_until and not self.adult_mode_active:
            self.state.adult_mode_until = None
            self.store.schedule_save()

    def _credit(self, seconds: int, playing: dict[str, Any], hour: int) -> None:
        if seconds <= 0:
            return
        s = self.state
        if self.decision.state == STATE_SCHEDULE:
            s.schedule_seconds += seconds
        else:
            s.used_seconds += seconds
        s.hour_seconds[hour] += seconds
        for field, bucket in (
            ("key", s.track_seconds),
            ("artist", s.artist_seconds),
            ("album", s.album_seconds),
            ("source", s.source_seconds),
        ):
            if value := playing.get(field):
                bucket[value] = bucket.get(value, 0) + seconds
        if key := playing.get("key"):
            self.activity.note_seconds(key, seconds)

    # ---- decisions ---------------------------------------------------------------

    def _active_schedule(self, now: datetime) -> Schedule | None:
        """A schedule this profile started, still inside its time, that lifts limits."""
        for sched in self.schedules:
            if not (sched.enabled and sched.lift_limits):
                continue
            run = self.state.schedule_runs.get(sched.id, {})
            for occ in sched.occurrences(now):
                if occ.contains(now) and run.get("started") == occ.key and run.get("stopped") != occ.key:
                    return sched
        return None

    @callback
    def _recompute(self, *, fire_events: bool = True) -> None:
        previous = self.decision
        now = dt_util.now()
        sched = self._active_schedule(now)
        self.decision = decide(
            now=now.time(),
            mode=self.state.mode,
            adult_mode=self.adult_mode_active,
            force_block=self.state.force_block,
            budget_minutes=self.daily_budget,
            extension_minutes=self.state.extension_minutes,
            used_seconds=self.state.used_seconds,
            warn_minutes=self.warn_minutes,
            quiet_windows=self.quiet_windows,
            schedule=sched.name if sched else None,
        )
        if not fire_events:
            return
        d = self.decision
        if (previous.state, previous.reason, previous.schedule) != (d.state, d.reason, d.schedule):
            _LOGGER.info("Media Mgmt %s: %s -> %s (%s)", self.name, previous.state, d.state, d.reason)
            self._log(act.EV_ENFORCEMENT, state=d.state, reason=d.reason, quiet_window=d.quiet_window, schedule=d.schedule)
            self.hass.bus.async_fire(
                EVENT_ENFORCEMENT_CHANGED,
                {
                    "profile_id": self.entry.entry_id,
                    "speaker": self.name,
                    ATTR_ENTITY_ID: self.entity_id,
                    "state": d.state,
                    "previous_state": previous.state,
                    "reason": d.reason,
                    "quiet_window": d.quiet_window,
                    "schedule": d.schedule,
                },
            )
        if d.state == STATE_WARNING and previous.state != STATE_WARNING:
            minutes = round((d.remaining_seconds or 0) / 60)
            if self._enforcing() and self.player.is_playing and self.announcer:
                self.announcer.announce(warning_message(minutes))
            self.hass.bus.async_fire(
                EVENT_WARNING,
                {"profile_id": self.entry.entry_id, "speaker": self.name, "remaining_minutes": minutes},
            )

    # ---- enforcement -------------------------------------------------------------

    @callback
    def _evaluate(self) -> None:
        self._enforce_stop()
        self._enforce_filter()
        self._enforce_volume()
        self._check_sleep_timer()

    # Stop music while it isn't allowed ------------------------------------------------

    @callback
    def _enforce_stop(self) -> None:
        blocking = self.decision.state == STATE_ENFORCING and self._enforcing()
        if not blocking or not self.player.is_playing:
            # The block ended, or the music stopped: the next play gets
            # announced and stopped afresh.
            self._stop_announced = False
            self._stop_attempts = 0
            if self._unsub_stop:
                self._unsub_stop()
                self._unsub_stop = None
            return
        if self._unsub_stop is not None:
            return
        delay = ACT_DELAY
        if self._stop_attempts:
            delay = self._retry_delay()
        elif not self._stop_announced and self.announcer and self.announcer.announce(
            stopping_message(self.decision.reason, self.decision.quiet_window)
        ):
            self._stop_announced = True
            delay = ANNOUNCE_GRACE
        self._unsub_stop = async_call_later(self.hass, delay, self._stop_callback)

    @callback
    def _stop_callback(self, _now: datetime) -> None:
        self._unsub_stop = None
        if not (self.decision.state == STATE_ENFORCING and self._enforcing() and self.player.is_playing):
            return
        now = dt_util.utcnow()
        wait = self._retry_delay() if self._stop_attempts else ACT_COOLDOWN
        if self._last_stop and (now - self._last_stop).total_seconds() < wait:
            self._unsub_stop = async_call_later(
                self.hass, wait - (now - self._last_stop).total_seconds(), self._stop_callback
            )
            return
        self._last_stop = now
        self._stop_attempts += 1
        action = self.player.resolve_action(self.limit_action)
        if self._stop_attempts == 1:
            self._log(act.EV_STOPPED, reason=self.decision.reason, action=action)
            _LOGGER.info("Media Mgmt %s: stopping music (%s)", self.name, self.decision.reason)
        self.hass.async_create_task(self.player.async_do(action))

    def _retry_delay(self) -> float:
        """10 s, 20 s, 40 s ... up to 10 min between tries."""
        return float(min(ACT_COOLDOWN * 2 ** max(0, self._stop_attempts - 1), MAX_ACT_RETRY))

    # Blocked music ----------------------------------------------------------------------

    def blocked_rule(self, media: dict[str, Any] | None = None) -> tuple[str, str] | None:
        """The rule what's playing breaks, if the filter is on."""
        if not self.state.music_filter:
            return None
        return self.filter.match(media if media is not None else self.player.media)

    @callback
    def _enforce_filter(self) -> None:
        media = self.player.media if self.player.is_playing else None
        key = media_id(media)
        if key != self._filter_key:
            self._filter_key = None
            self._filter_tries = 0
            if self._unsub_filter:
                self._unsub_filter()
                self._unsub_filter = None
        if media is None or not self.decision.filter_active or key == self._filter_key:
            return
        rule = self.blocked_rule(media)
        if rule is None:
            return
        self._filter_key = key
        kind, value = rule
        acted = self._enforcing()
        action = self.player.resolve_action(self.filter_action)
        now = dt_util.utcnow()
        self.state.blocked_count += 1
        self.state.last_blocked = describe(media)
        self.state.last_blocked_at = now.isoformat()
        self.store.schedule_save()
        self._log(
            act.EV_BLOCKED, kind=kind, rule=value, title=media.get("title"), artist=media.get("artist"),
            album=media.get("album"), source=media.get("source"), action=action, acted=acted,
        )
        self.hass.bus.async_fire(
            EVENT_MEDIA_BLOCKED,
            {
                "profile_id": self.entry.entry_id,
                "speaker": self.name,
                ATTR_ENTITY_ID: self.entity_id,
                "title": media.get("title"),
                "artist": media.get("artist"),
                "album": media.get("album"),
                "source": media.get("source"),
                "rule_kind": kind,
                "rule": value,
                "action": action,
                "acted": acted,
            },
        )
        _LOGGER.info("Media Mgmt %s: blocked %s (%s %s)", self.name, describe(media), kind, value)
        if acted:
            self._unsub_filter = async_call_later(self.hass, ACT_DELAY, self._filter_callback)

    @callback
    def _filter_callback(self, _now: datetime) -> None:
        self._unsub_filter = None
        media = self.player.media if self.player.is_playing else None
        if media is None or media_id(media) != self._filter_key or not self._enforcing():
            return
        if self.blocked_rule(media) is None or not self.decision.filter_active:
            return
        self._filter_tries += 1
        action = self.player.resolve_action(self.filter_action)
        self.hass.async_create_task(self.player.async_do(action))
        if self._filter_tries < MAX_FILTER_TRIES:
            # Check again: some speakers ignore a skip mid-buffer.
            self._unsub_filter = async_call_later(self.hass, ACT_COOLDOWN, self._filter_callback)

    # Volume cap --------------------------------------------------------------------------

    @callback
    def _enforce_volume(self) -> None:
        cap = self.max_volume
        volume = self.player.volume
        if cap >= 100 or volume is None or self._fade:
            return
        if self.decision.state not in (STATE_OK, STATE_WARNING, STATE_SCHEDULE, STATE_ENFORCING):
            return  # paused or adult mode
        if not self.player.is_on or volume * 100 <= cap + 0.5:
            return
        now = dt_util.utcnow()
        if self._last_volume_fix and (now - self._last_volume_fix).total_seconds() < (2 * VOLUME_COOLDOWN if not self._enforcing() else VOLUME_COOLDOWN):
            return
        self._last_volume_fix = now
        acted = self._enforcing()
        if not self._last_volume_log or now - self._last_volume_log > VOLUME_LOG_EVERY:
            self._last_volume_log = now
            self._log(act.EV_VOLUME, **{"from": round(volume * 100), "to": cap, "acted": acted})
        if acted:
            self.hass.async_create_task(self.player.async_set_volume(cap / 100))

    # Sleep timer -------------------------------------------------------------------------

    @callback
    def _check_sleep_timer(self) -> None:
        until = self.state.sleep_until_dt
        if until is None:
            return
        now = dt_util.utcnow()
        if now >= until:
            self.state.sleep_until = None
            self.store.schedule_save()
            self._log(act.EV_SLEEP, action="fired")
            self._finish_fade_and_stop(ACTION_PAUSE, reason="sleep_timer")
            return
        fade = self.state.sleep_fade
        if fade and now >= until - timedelta(minutes=fade) and not self._fade and self.player.is_playing:
            self._start_fade(until - timedelta(minutes=fade), until, reason="sleep_timer")

    @callback
    def set_sleep_timer(self, minutes: int, fade: int = 0, by: str | None = None) -> None:
        self.state.sleep_until = (dt_util.utcnow() + timedelta(minutes=minutes)).isoformat()
        self.state.sleep_fade = max(0, min(fade, minutes))
        self._log(act.EV_SLEEP, action="set", minutes=minutes, fade=self.state.sleep_fade or None, by=by)
        self.store.schedule_save()
        self._evaluate()
        self.notify()

    @callback
    def cancel_sleep_timer(self, by: str | None = None) -> None:
        if self.state.sleep_until:
            self._log(act.EV_SLEEP, action="cancelled", by=by)
        self.state.sleep_until = None
        if self._fade and self._fade.get("reason") == "sleep_timer":
            self._cancel_fade(restore=True)
        self.store.schedule_save()
        self.notify()

    # Fading out --------------------------------------------------------------------------

    @callback
    def _start_fade(self, begin: datetime, until: datetime, *, reason: str) -> None:
        """Turn the volume down steadily from `begin` to `until`."""
        volume = self.player.volume
        if volume is None or not self.player.supports(F.VOLUME_SET):
            return
        self._fade = {"from": volume, "start": min(begin, dt_util.utcnow()), "until": until, "reason": reason}
        self.state.fade_restore = volume
        self.store.schedule_save()
        self._unsub_fade = async_track_time_interval(
            self.hass, self._fade_step, timedelta(seconds=FADE_STEP), name=f"media_mgmt fade {self.name}"
        )
        self._fade_step(dt_util.utcnow())

    @callback
    def _fade_step(self, _now: datetime) -> None:
        fade = self._fade
        if not fade:
            return
        if not self.player.is_playing:
            self._cancel_fade(restore=True)
            return
        now = dt_util.utcnow()
        total = (fade["until"] - fade["start"]).total_seconds() or 1
        left = max(0.0, (fade["until"] - now).total_seconds() / total)
        level = max(FADE_FLOOR, fade["from"] * left)
        self.hass.async_create_task(self.player.async_set_volume(level))

    @callback
    def _cancel_fade(self, *, restore: bool) -> None:
        if self._unsub_fade:
            self._unsub_fade()
            self._unsub_fade = None
        self._fade = None
        if restore:
            self._restore_volume()

    @callback
    def _restore_volume(self) -> None:
        level = self.state.fade_restore
        self.state.fade_restore = None
        self.store.schedule_save()
        if level is not None:
            cap = self.max_volume / 100
            self.hass.async_create_task(self.player.async_set_volume(min(level, cap)))

    @callback
    def _finish_fade_and_stop(self, action: str, *, reason: str) -> None:
        """Stop the music, then put the volume back for next time."""
        self._cancel_fade(restore=False)
        playing = self.player.is_playing

        async def _run() -> None:
            if playing:
                await self.player.async_do(self.player.resolve_action(action))
            if self.state.fade_restore is not None:
                self._restore_volume()

        if playing:
            self._log(act.EV_STOPPED, reason=reason, action=self.player.resolve_action(action))
        self.hass.async_create_task(_run())

    # ---- schedules ---------------------------------------------------------------

    @callback
    def _check_schedules(self) -> None:
        now = dt_util.now()
        for sched in self.schedules:
            if not sched.enabled:
                continue
            run = self.state.schedule_runs.setdefault(sched.id, {})
            for occ in sched.occurrences(now):
                if occ.stop_due(now):
                    if run.get("stopped") != occ.key:
                        run["stopped"] = occ.key
                        self.store.schedule_save()
                        self._schedule_stop(sched)
                    continue
                if occ.fade_due(now) and run.get("faded") != occ.key and self.player.is_playing and not self._fade:
                    run["faded"] = occ.key
                    self.store.schedule_save()
                    self._log(act.EV_SCHEDULE, id=sched.id, name=sched.name, action="fading", minutes=sched.fade_minutes)
                    self._start_fade(occ.fade_from, occ.stop, reason=f"schedule:{sched.id}")
                if occ.start_due(now) and run.get("started") != occ.key:
                    run["started"] = occ.key
                    self.store.schedule_save()
                    self.hass.async_create_task(self.async_start_schedule(sched))

    @callback
    def _schedule_stop(self, sched: Schedule) -> None:
        playing = self.player.is_playing
        self._log(act.EV_SCHEDULE, id=sched.id, name=sched.name, action="stopped" if playing else "stop_idle")
        self._fire_schedule(sched, "stopped")
        if playing or self.state.fade_restore is not None:
            self._finish_fade_and_stop(sched.stop_action, reason="schedule")
        self._recompute()

    def _fire_schedule(self, sched: Schedule, action: str, detail: str | None = None) -> None:
        self.hass.bus.async_fire(
            EVENT_SCHEDULE,
            {
                "profile_id": self.entry.entry_id,
                "speaker": self.name,
                ATTR_ENTITY_ID: self.entity_id,
                "schedule_id": sched.id,
                "schedule": sched.name,
                "action": action,
                "detail": detail,
            },
        )

    async def async_start_schedule(
        self, sched: Schedule, *, by: str | None = None, manual: bool = False
    ) -> bool:
        """Start a schedule's music now. Returns True if the speaker took it."""
        player = self.player
        if manual:
            # Started by hand inside its time: it lifts limits until its stop time.
            now = dt_util.now()
            run = self.state.schedule_runs.setdefault(sched.id, {})
            for occ in sched.occurrences(now):
                if occ.contains(now):
                    run["started"] = occ.key
            self.store.schedule_save()
        if self._fade:
            self._cancel_fade(restore=False)
        if player.is_on is False:
            await player.async_turn_on()
        if sched.volume is not None and player.supports(F.VOLUME_SET):
            await player.async_set_volume(min(sched.volume, self.max_volume) / 100)
        ok, detail = await self._play(sched)
        if ok:
            if sched.play_kind != PLAY_SOURCE:
                await player.async_shuffle(sched.shuffle)
                await player.async_repeat(sched.repeat)
            self._log(act.EV_SCHEDULE, id=sched.id, name=sched.name, action="started", detail=detail, by=by)
            self._fire_schedule(sched, "started", detail)
        else:
            self._log(act.EV_SCHEDULE, id=sched.id, name=sched.name, action="failed", detail=detail, by=by)
            self._fire_schedule(sched, "failed", detail)
            _LOGGER.warning("Media Mgmt %s: schedule %s couldn't play: %s", self.name, sched.name, detail)
        self._recompute()
        self._evaluate()
        self.notify()
        return ok

    async def _play(self, sched: Schedule) -> tuple[bool, str]:
        """Play what the schedule asks for, the best way this speaker allows."""
        player = self.player
        kind, value = sched.play_kind, sched.play_value
        if kind == PLAY_RESUME:
            return await player.async_play(), "resumed"
        if kind == PLAY_SOURCE:
            return await player.async_select_source(value), f"source {value}"
        if kind == PLAY_CONTENT:
            return await player.async_play_media(value, sched.content_type or "music", enqueue="replace"), value
        # Artist, album, song or playlist
        if _looks_like_uri(value):
            return await player.async_play_media(value, sched.content_type or kind, enqueue="replace"), value
        if player.is_music_assistant:
            return (
                await player.async_music_assistant(value, kind, radio=False),
                f"{kind} {value} with Music Assistant",
            )
        if item := self._library_match(kind, value):
            content_id, content_type = item["content_id"], item.get("content_type") or "music"
            return await player.async_play_media(content_id, content_type, enqueue="replace"), (
                f"{item.get('title')} from {kind} {value}"
            )
        return False, (
            f"This speaker can't search for the {kind} {value!r}. Link it through Music Assistant, "
            "or play a playlist, a favourite (source) or a media ID instead."
        )

    def _library_match(self, kind: str, value: str) -> dict[str, Any] | None:
        """The most played song from the library that fits, with an ID the speaker can play."""
        field = {"artist": "artist", "album": "album", "track": "title", "playlist": "playlist"}.get(kind)
        wanted = norm(value)
        best = None
        for item in self.activity.library.values():
            if not item.get("content_id") or norm(item.get(field) or "") != wanted:
                continue
            if self.filter.match(item):
                continue
            if best is None or item.get("plays", 0) > best.get("plays", 0):
                best = item
        return best

    # Editing schedules (from the sidebar app) ----------------------------------------------

    @callback
    def save_schedule(self, data: dict[str, Any], by: str | None = None) -> Schedule:
        sched = Schedule.from_dict(data)
        if sched.volume is not None:
            sched.volume = min(sched.volume, self.max_volume)
        existing = next((i for i, s in enumerate(self.schedules) if s.id == sched.id), None)
        if existing is None:
            self.schedules.append(sched)
            # Created during its own start time: don't start it until next time.
            now = dt_util.now()
            run = self.state.schedule_runs.setdefault(sched.id, {})
            for occ in sched.occurrences(now):
                if occ.start and occ.start <= now:
                    run["started"] = occ.key
                if occ.stop and occ.stop <= now:
                    run["stopped"] = occ.key
        else:
            self.schedules[existing] = sched
        self.schedule_store.schedule_save()
        self.store.schedule_save()
        self._recompute()
        self.notify()
        return sched

    @callback
    def delete_schedule(self, schedule_id: str) -> bool:
        before = len(self.schedules)
        self.schedule_store.schedules = [s for s in self.schedules if s.id != schedule_id]
        self.state.schedule_runs.pop(schedule_id, None)
        self.schedule_store.schedule_save()
        self.store.schedule_save()
        self._recompute()
        self.notify()
        return len(self.schedules) != before

    def schedule_by_id(self, schedule_id: str) -> Schedule | None:
        return next((s for s in self.schedules if s.id == schedule_id), None)

    # ---- parent controls -----------------------------------------------------------

    @callback
    def _changed(self) -> None:
        self.store.schedule_save()
        self._recompute()
        self._filter_key = None
        self._evaluate()
        self.notify()

    @callback
    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(mode)
        if self.state.mode != mode:
            self.state.mode = mode
            self._log(act.EV_MODE, mode=mode)
            self._changed()

    @callback
    def set_music_filter(self, enabled: bool) -> None:
        if self.state.music_filter != enabled:
            self.state.music_filter = enabled
            self._log(act.EV_FILTER, on=enabled)
            self._changed()

    @callback
    def set_adult_mode(self, enabled: bool, minutes: int | None = None) -> None:
        if enabled:
            duration = minutes or self.adult_mode_duration
            self.state.adult_mode_until = (dt_util.utcnow() + timedelta(minutes=duration)).isoformat()
            self._log(act.EV_ADULT_MODE, on=True, minutes=duration)
        else:
            if self.adult_mode_active:
                self._log(act.EV_ADULT_MODE, on=False)
            self.state.adult_mode_until = None
        self._changed()

    @callback
    def grant_extension(self, minutes: int) -> None:
        self._count_usage()
        self._snapshot()
        self.state.extension_minutes += minutes
        self._log(act.EV_EXTENSION, minutes=minutes)
        self._changed()

    @callback
    def force_block(self) -> None:
        if not self.state.force_block:
            self._log(act.EV_BLOCK)
        self.state.force_block = True
        self._changed()

    @callback
    def unblock(self) -> None:
        if self.state.force_block:
            self._log(act.EV_UNBLOCK)
        self.state.force_block = False
        self._changed()

    @callback
    def reset_usage(self) -> None:
        self.state.reset_day(dt_util.now().date())
        self._last_tick = dt_util.utcnow()
        self._log(act.EV_RESET)
        self._changed()

    def filter_rules(self) -> dict[str, list[str]]:
        return self.filter.as_dict()

    @callback
    def update_filter(self, kind: str, value: str, *, add: bool, by: str | None = None) -> bool:
        """Add or remove a music filter rule. Saved in the profile's options."""
        if kind not in BLOCK_KINDS or not value.strip():
            raise ValueError(kind)
        rules = self.filter_rules()
        changed = add_rule(rules, kind, value) if add else remove_rule(rules, kind, value)
        if not changed:
            return False
        self._log(act.EV_RULE, kind=kind, value=" ".join(value.split()), added=add, by=by)
        self.save_filter(rules)
        return True

    @callback
    def save_filter(self, rules: dict[str, list[str]], action: str | None = None) -> None:
        options = {k: (dict(v) if isinstance(v, dict) else v) for k, v in self.entry.options.items()}
        section = options.setdefault(SECTION_FILTER, {})
        for kind, conf in BLOCK_KINDS.items():
            if kind in rules:
                section[conf] = clean_list(rules[kind])
        if action:
            section[CONF_FILTER_ACTION] = action
        # The update listener applies it without reloading the profile.
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    # ---- output --------------------------------------------------------------------

    @callback
    def notify(self) -> None:
        self._record_today()
        async_dispatcher_send(self.hass, SIGNAL_UPDATED.format(self.entry.entry_id))
        async_dispatcher_send(self.hass, SIGNAL_ANY_UPDATED, self.entry.entry_id)

    @callback
    def _log(self, event_type: str, **data: Any) -> None:
        self.activity.add(dt_util.utcnow(), event_type, **data)
        self.activity_store.schedule_save()

    @callback
    def _log_state(self) -> None:
        state = self.player.state
        if state is None or state == self._logged_state:
            return
        self._logged_state = state
        media = self.player.media
        self._log(act.EV_STATE, state=state, source=(media or {}).get("source"))

    @callback
    def _resume_logged_play(self) -> None:
        """After a restart, a song still playing isn't a new play."""
        last = self.activity.last_play
        media = self.player.media if self.player.is_playing else None
        if not (last and media):
            return
        if dt_util.utcnow() - datetime.fromisoformat(last["t"]) > RESUME_PLAY_WITHIN:
            return
        if all(last.get(k) == media.get(k) for k in ("title", "artist", "album")):
            self._logged_play = media_id(media)

    @callback
    def _log_play(self) -> None:
        """Log each new song once, when it starts playing."""
        if not self.player.is_playing:
            return
        media = self.player.media
        ident = media_id(media)
        if ident is None or ident == self._logged_play:
            return
        self._logged_play = ident
        key = track_key(media)
        self.state.plays += 1
        self.store.schedule_save()
        self.activity.note_play(dt_util.utcnow(), key, media)
        self._log(
            act.EV_PLAY, key=key, title=media.get("title"), artist=media.get("artist"),
            album=media.get("album"), source=media.get("source"),
        )

    @callback
    def _record_today(self) -> None:
        s = self.state
        if self.activity.record_day(
            s.day,
            used_seconds=s.used_seconds,
            budget_minutes=self.daily_budget,
            extension_minutes=s.extension_minutes,
            blocked=s.blocked_count,
            plays=s.plays,
            tracks=s.track_seconds,
            artists=s.artist_seconds,
            albums=s.album_seconds,
            sources=s.source_seconds,
            hours=s.hour_seconds,
            schedule_seconds=s.schedule_seconds,
        ):
            self.activity_store.schedule_save()
