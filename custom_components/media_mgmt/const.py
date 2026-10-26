"""Constants for Media Mgmt."""

from __future__ import annotations

DOMAIN = "media_mgmt"
NAME = "Media Mgmt"

CONF_MEDIA_PLAYER = "media_player"
MUSIC_ASSISTANT_DOMAIN = "music_assistant"

# Option sections (config/options form groups)
SECTION_LISTENING = "listening"
SECTION_FILTER = "filter"
SECTION_VOLUME = "volume"
SECTION_ANNOUNCE = "announcements"
SECTION_PLAYBACK = "playback"

# Playing music: the Music Assistant player to play through, picked by hand
# when Media Mgmt can't find the speaker's one itself.
CONF_MA_PLAYER = "music_assistant_player"

# Listening time
CONF_DAILY_BUDGET = "daily_budget"  # minutes, 0 = unlimited
CONF_WARN_MINUTES = "warn_minutes"
CONF_QUIET_WINDOWS = "quiet_windows"
CONF_LIMIT_ACTION = "limit_action"  # pause / stop / turn_off, when music isn't allowed
CONF_ADULT_MODE_DURATION = "adult_mode_duration"  # minutes

DEFAULT_DAILY_BUDGET = 0
DEFAULT_WARN_MINUTES = 5
DEFAULT_QUIET_WINDOWS = ""
DEFAULT_ADULT_MODE_DURATION = 120

# What Media Mgmt does to the speaker
ACTION_SKIP = "skip"
ACTION_PAUSE = "pause"
ACTION_STOP = "stop"
ACTION_TURN_OFF = "turn_off"
LIMIT_ACTIONS = [ACTION_PAUSE, ACTION_STOP, ACTION_TURN_OFF]
FILTER_ACTIONS = [ACTION_SKIP, ACTION_PAUSE, ACTION_STOP]
DEFAULT_LIMIT_ACTION = ACTION_PAUSE
DEFAULT_FILTER_ACTION = ACTION_SKIP

# Blocked music: kind -> option key holding its list
CONF_BLOCKED_TRACKS = "blocked_tracks"
CONF_BLOCKED_ARTISTS = "blocked_artists"
CONF_BLOCKED_ALBUMS = "blocked_albums"
CONF_BLOCKED_SOURCES = "blocked_sources"
CONF_BLOCKED_KEYWORDS = "blocked_keywords"
CONF_FILTER_ACTION = "filter_action"  # skip / pause / stop
BLOCK_KINDS = {
    "track": CONF_BLOCKED_TRACKS,
    "artist": CONF_BLOCKED_ARTISTS,
    "album": CONF_BLOCKED_ALBUMS,
    "source": CONF_BLOCKED_SOURCES,
    "keyword": CONF_BLOCKED_KEYWORDS,
}

# Volume cap
CONF_MAX_VOLUME = "max_volume"  # percent, 100 = no cap
DEFAULT_MAX_VOLUME = 100

# Spoken warnings
CONF_ANNOUNCE_TTS = "announce_tts"
CONF_ANNOUNCE_ON_PLAYER = "announce_on_player"
CONF_ANNOUNCE_PLAYERS = "announce_players"
ANNOUNCE_GRACE = 8  # seconds between "the music is stopping" and stopping it

# How often listening is counted and timers, schedules and fades are checked.
TICK_INTERVAL = 15  # seconds
# Wait after music starts (or a blocked song starts) before acting on it.
ACT_DELAY = 2  # seconds
# Don't send the same command more often than this; tries after that wait longer.
ACT_COOLDOWN = 10  # seconds
MAX_ACT_RETRY = 600  # seconds
# Don't fight someone turning the volume up more often than this.
VOLUME_COOLDOWN = 2  # seconds
# How often the volume is lowered while fading out.
FADE_STEP = 10  # seconds

# Services
SERVICE_GRANT_EXTENSION = "grant_extension"
SERVICE_FORCE_BLOCK = "force_block"
SERVICE_UNBLOCK = "unblock"
SERVICE_RESET_USAGE = "reset_usage"
SERVICE_BLOCK_MEDIA = "block_media"
SERVICE_UNBLOCK_MEDIA = "unblock_media"
SERVICE_SET_SLEEP_TIMER = "set_sleep_timer"
SERVICE_CANCEL_SLEEP_TIMER = "cancel_sleep_timer"
SERVICE_RUN_SCHEDULE = "run_schedule"
SERVICE_PLAY_ARTIST = "play_artist"
ATTR_PROFILE_ID = "profile_id"
ATTR_MINUTES = "minutes"

# Events
EVENT_MEDIA_BLOCKED = f"{DOMAIN}_media_blocked"
EVENT_ENFORCEMENT_CHANGED = f"{DOMAIN}_enforcement_changed"
EVENT_WARNING = f"{DOMAIN}_warning"
EVENT_SCHEDULE = f"{DOMAIN}_schedule"
EVENT_PLAY = f"{DOMAIN}_play"

# Voice and AI assistants: "play Brahms in the kids room"
INTENT_PLAY_ARTIST = "MediaMgmtPlayArtist"

SIGNAL_UPDATED = f"{DOMAIN}_updated_{{}}"
SIGNAL_ANY_UPDATED = f"{DOMAIN}_any_updated"
SIGNAL_ARTISTS_UPDATED = f"{DOMAIN}_artists_updated"
