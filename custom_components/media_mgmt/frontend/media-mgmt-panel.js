// Media Mgmt sidebar app. Plain web component, no build step.
// Talks to the integration over Home Assistant's websocket (media_mgmt/* commands).
// Everything Media Mgmt does can be set up and changed from here.

const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "activity", label: "Activity" },
  { id: "analytics", label: "Analytics" },
  { id: "library", label: "Played music" },
  { id: "schedules", label: "Schedules" },
  { id: "rules", label: "Rules" },
];

const MODES = [
  { id: "enforced", label: "Enforced" },
  { id: "monitor_only", label: "Monitor only" },
  { id: "paused", label: "Paused" },
];

const RANGES = [7, 30, 90];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; // Python weekday order
const DAY_PRESETS = [
  { label: "Every day", days: [0, 1, 2, 3, 4, 5, 6] },
  { label: "School nights", days: [6, 0, 1, 2, 3] },
  { label: "Weekends", days: [4, 5] },
];
const KIND_LABELS = { track: "Song", artist: "Artist", album: "Album", source: "App or source", keyword: "Word in a title" };
const KIND_PLURAL = { track: "Songs", artist: "Artists", album: "Albums", source: "Apps and sources", keyword: "Words in a title" };
const PLAY_KINDS = [
  { id: "artist", label: "An artist" },
  { id: "playlist", label: "A playlist" },
  { id: "album", label: "An album" },
  { id: "track", label: "A song" },
  { id: "source", label: "A favourite or source" },
  { id: "content", label: "A media ID (URI)" },
  { id: "resume", label: "Whatever played last" },
];
const STOP_ACTIONS = [
  { id: "pause", label: "Pause" },
  { id: "stop", label: "Stop" },
  { id: "turn_off", label: "Turn the speaker off" },
];
const LIMIT_ACTIONS = STOP_ACTIONS;
const FILTER_ACTIONS = [
  { id: "skip", label: "Skip to the next song" },
  { id: "pause", label: "Pause the music" },
  { id: "stop", label: "Stop the music" },
];
const SLEEP_PRESETS = [15, 30, 45, 60];
const SEP = " — ";

// Colours for artists on the activity strip, chosen to stay apart in light and dark themes.
const COLOURS = ["#5c6bc0", "#26a69a", "#ab47bc", "#ffa726", "#29b6f6", "#ec407a", "#8d9aa5"];

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const minutes = (seconds) => Math.round((seconds || 0) / 60);

function duration(seconds) {
  const total = minutes(seconds);
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

const timeOf = (iso) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

function hhmmLabel(hhmm) {
  if (!hhmm) return "";
  const [h, m] = hhmm.split(":").map(Number);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function whenLabel(iso) {
  const d = new Date(iso);
  const now = new Date();
  const days = Math.round((new Date(d.toDateString()) - new Date(now.toDateString())) / 86400000);
  const day = days === 0 ? "Today" : days === 1 ? "Tomorrow" : days === -1 ? "Yesterday" : d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  return `${day} at ${timeOf(iso)}`;
}

function agoLabel(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const days = Math.round((new Date(new Date().toDateString()) - new Date(d.toDateString())) / 86400000);
  if (days === 0) return `Today ${timeOf(iso)}`;
  if (days === 1) return `Yesterday ${timeOf(iso)}`;
  if (days < 7) return d.toLocaleDateString([], { weekday: "long" });
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
}

function dayLabel(isoDate, today) {
  if (isoDate === today) return "Today";
  const d = new Date(`${isoDate}T12:00:00`);
  const t = new Date(`${today}T12:00:00`);
  if ((t - d) / 86400000 === 1) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
}

function shiftDate(isoDate, days) {
  const d = new Date(`${isoDate}T12:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function daysLabel(days) {
  const set = [...days].sort().join(",");
  const preset = DAY_PRESETS.find((p) => [...p.days].sort().join(",") === set);
  if (preset) return preset.label;
  return days.length ? [...days].sort().map((d) => DAYS[d]).join(", ") : "No days";
}

const songOf = (key) => {
  const i = (key || "").indexOf(SEP);
  return i < 0 ? { title: key, artist: null } : { title: key.slice(0, i), artist: key.slice(i + SEP.length) };
};
const trackEntry = (title, artist) => (artist ? `${title}${SEP}${artist}` : title);

function stateInfo(p) {
  switch (p.state) {
    case "enforcing": {
      const why = { budget: "Daily limit reached", quiet_window: p.quiet_window || "Quiet window", manual: "Blocked by a parent" }[p.reason];
      return { tone: "bad", text: why || "Blocked" };
    }
    case "warning":
      return { tone: "warn", text: `${minutes(p.remaining_seconds)} min left` };
    case "paused":
      return { tone: "muted", text: "Rules paused" };
    case "adult_mode":
      return { tone: "info", text: p.adult_mode_until ? `Adult mode until ${timeOf(p.adult_mode_until)}` : "Adult mode" };
    case "schedule":
      return { tone: "info", text: `${p.schedule || "Schedule"} playing` };
    default:
      return { tone: "good", text: p.mode === "monitor_only" ? "Monitoring" : "OK" };
  }
}

function describeEvent(e) {
  const song = e.title ? `${e.title}${e.artist ? ` by ${e.artist}` : ""}` : "a song";
  const by = e.by ? ` by ${e.by}` : "";
  switch (e.type) {
    case "state":
      return {
        icon: e.state === "playing" ? "play" : e.state === "off" ? "power" : "pause",
        text: { playing: "Started playing", paused: "Paused", idle: "Stopped", off: "Speaker turned off", on: "Speaker turned on", unavailable: "Speaker went offline" }[e.state] || `Speaker ${e.state}`,
      };
    case "play":
      return { icon: "note", text: `Played ${song}${e.source ? ` on ${e.source}` : ""}`, song: true };
    case "blocked": {
      const rule = `${KIND_LABELS[e.kind]?.toLowerCase() ?? e.kind} “${e.rule}”`;
      const did = !e.acted ? " (monitor only)" : { skip: ", skipped it", pause: ", paused", stop: ", stopped", turn_off: ", turned the speaker off" }[e.action] || "";
      return { icon: "shield", tone: e.acted ? "bad" : "warn", text: `Blocked ${song}: ${rule}${did}`, song: true };
    }
    case "enforcement": {
      const text =
        e.state === "enforcing"
          ? { budget: "Daily limit reached", quiet_window: `Quiet window started${e.quiet_window ? `: ${e.quiet_window}` : ""}`, manual: "Blocked by a parent" }[e.reason] || "Blocked"
          : { warning: "Listening time is almost up", ok: "Allowed to listen again", paused: "Rules paused", adult_mode: "Adult mode started", schedule: `${e.schedule || "Schedule"} lifted the limits` }[e.state] || e.state;
      return { icon: "clock", tone: e.state === "enforcing" ? "bad" : e.state === "warning" ? "warn" : undefined, text };
    }
    case "stopped": {
      const why = { budget: "the daily limit", quiet_window: "a quiet window", manual: "a parent's block", sleep_timer: "the sleep timer", schedule: "a schedule" }[e.reason] || e.reason;
      return { icon: "stop", tone: "bad", text: `Media Mgmt ${e.action === "turn_off" ? "turned the speaker off" : e.action === "stop" ? "stopped the music" : "paused the music"} for ${why}` };
    }
    case "mode":
      return { icon: "mode", text: `Mode set to ${MODES.find((m) => m.id === e.mode)?.label ?? e.mode}` };
    case "filter":
      return { icon: "shield", text: e.on ? "Music filter turned on" : "Music filter turned off" };
    case "adult_mode":
      return { icon: "adult", text: e.on ? `Adult mode on for ${e.minutes} min` : "Adult mode turned off" };
    case "extension":
      return { icon: "plus", text: e.minutes >= 0 ? `${e.minutes} min of extra time added` : `${-e.minutes} min taken away` };
    case "block":
      return { icon: "stop", tone: "bad", text: "Blocked now" };
    case "unblock":
      return { icon: "play", text: "Unblocked" };
    case "reset":
      return { icon: "clock", text: "Today's time reset" };
    case "volume":
      return { icon: "volume", tone: e.acted ? undefined : "warn", text: `Volume turned up to ${e.from}%, ${e.acted ? `turned back down to ${e.to}%` : `over the ${e.to}% cap (monitor only)`}${e.schedule ? `, the limit during ${e.schedule}` : ""}` };
    case "rule":
      return { icon: "shield", text: `${e.added ? "Blocked" : "Unblocked"} ${KIND_LABELS[e.kind]?.toLowerCase() ?? e.kind} “${e.value}”${by}` };
    case "schedule": {
      const what = { started: "started", fading: `fading out over ${e.minutes} min`, stopped: "stopped the music", stop_idle: "ended (nothing was playing)", failed: "couldn't play", limit_started: `started: volume limited to ${e.limit}%`, limit_ended: "ended: volume limit lifted" }[e.action] || e.action;
      return { icon: "calendar", tone: e.action === "failed" ? "bad" : undefined, text: `${e.name} ${what}${e.detail && e.action !== "started" ? `: ${e.detail}` : e.detail ? ` (${e.detail})` : ""}${by}` };
    }
    case "sleep":
      return {
        icon: "sleep",
        text: e.action === "set" ? `Sleep timer set for ${e.minutes} min${e.fade ? `, fading out over the last ${e.fade}` : ""}${by}` : e.action === "cancelled" ? `Sleep timer cancelled${by}` : "Sleep timer ended",
      };
    default:
      return { icon: "clock", text: e.type };
  }
}

const EXPANDED_KEY = "media-mgmt-expanded";

// The volume cap right now: lower while a playing schedule limits it.
const capOf = (p) => p.volume_cap ?? p.max_volume;
const capLabel = (p) =>
  capOf(p) >= 100 ? "None" : p.volume_limit_schedule && capOf(p) < p.max_volume ? `${capOf(p)}% during ${p.volume_limit_schedule}` : `${capOf(p)}%`;

const ICONS = {
  "chevron-down": "M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z",
  play: "M8,5.14V19.14L19,12.14L8,5.14Z",
  pause: "M14,19H18V5H14M6,19H10V5H6V19Z",
  stop: "M18,18H6V6H18V18Z",
  speaker: "M12,12A3,3 0 0,0 9,15A3,3 0 0,0 12,18A3,3 0 0,0 15,15A3,3 0 0,0 12,12M12,20A5,5 0 0,1 7,15A5,5 0 0,1 12,10A5,5 0 0,1 17,15A5,5 0 0,1 12,20M12,4A2,2 0 0,1 14,6A2,2 0 0,1 12,8C10.89,8 10,7.1 10,6C10,4.89 10.89,4 12,4M17,2H7C5.89,2 5,2.89 5,4V20A2,2 0 0,0 7,22H17A2,2 0 0,0 19,20V4C19,2.89 18.1,2 17,2Z",
  prev: "M6,18V6H8V18H6M9.5,12L18,6V18L9.5,12Z",
  next: "M16,18H18V6H16M6,18L14.5,12L6,6V18Z",
  note: "M12,3V13.55C11.41,13.21 10.73,13 10,13A4,4 0 0,0 6,17A4,4 0 0,0 10,21A4,4 0 0,0 14,17V7H18V3H12Z",
  power: "M16.56,5.44L15.11,6.89C16.84,7.94 18,9.83 18,12A6,6 0 0,1 12,18A6,6 0 0,1 6,12C6,9.83 7.16,7.94 8.88,6.88L7.44,5.44C5.36,6.88 4,9.28 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12C20,9.28 18.64,6.88 16.56,5.44M13,3H11V13H13",
  shield: "M12,1L3,5V11C3,16.55 6.84,21.74 12,23C17.16,21.74 21,16.55 21,11V5L12,1Z",
  clock: "M12,20A8,8 0 0,0 20,12A8,8 0 0,0 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20M12,2A10,10 0 0,1 22,12A10,10 0 0,1 12,22C6.47,22 2,17.5 2,12A10,10 0 0,1 12,2M12.5,7V12.25L17,14.92L16.25,16.15L11,13V7H12.5Z",
  mode: "M12,1L3,5V11C3,16.55 6.84,21.74 12,23C17.16,21.74 21,16.55 21,11V5L12,1M12,7C13.4,7 14.8,8.1 14.8,9.5V11C15.4,11 16,11.6 16,12.3V15.8C16,16.4 15.4,17 14.7,17H9.2C8.6,17 8,16.4 8,15.7V12.2C8,11.6 8.6,11 9.2,11V9.5C9.2,8.1 10.6,7 12,7Z",
  adult: "M12,4A4,4 0 0,1 16,8A4,4 0 0,1 12,12A4,4 0 0,1 8,8A4,4 0 0,1 12,4M12,14C16.42,14 20,15.79 20,18V20H4V18C4,15.79 7.58,14 12,14Z",
  plus: "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z",
  left: "M15.41,16.58L10.83,12L15.41,7.41L14,6L8,12L14,18L15.41,16.58Z",
  right: "M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z",
  delete: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  volume: "M14,3.23V5.29C16.89,6.15 19,8.83 19,12C19,15.17 16.89,17.84 14,18.7V20.77C18,19.86 21,16.28 21,12C21,7.72 18,4.14 14,3.23M16.5,12C16.5,10.23 15.5,8.71 14,7.97V16C15.5,15.29 16.5,13.76 16.5,12M3,9V15H7L12,20V4L7,9H3Z",
  calendar: "M19,19H5V8H19M16,1V3H8V1H6V3H5C3.89,3 3,3.89 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5C21,3.89 20.1,3 19,3H18V1M17,12H12V17H17V12Z",
  sleep: "M23,12H17V10L20.39,6H17V4H23V6L19.62,10H23V12M15,16H9V14L12.39,10H9V8H15V10L11.62,14H15V16M7,20H1V18L4.39,14H1V12H7V14L3.62,18H7V20Z",
  block: "M12,2C17.5,2 22,6.5 22,12C22,17.5 17.5,22 12,22C6.5,22 2,17.5 2,12C2,6.5 6.5,2 12,2M12,4C10.1,4 8.4,4.6 7.1,5.7L18.3,16.9C19.3,15.5 20,13.8 20,12C20,7.6 16.4,4 12,4M16.9,18.3L5.7,7.1C4.6,8.4 4,10.1 4,12C4,16.4 7.6,20 12,20C13.9,20 15.6,19.4 16.9,18.3Z",
  edit: "M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z",
  search: "M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z",
};

const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name] ?? ICONS.clock}"/></svg>`;

const ENTITY_LABELS = {
  mode: "Mode",
  music_filter: "Music filter",
  adult_mode: "Adult mode",
  enforcement_state: "Enforcement state",
  now_playing: "Now playing",
  listening_time_today: "Listening time today",
  time_remaining_today: "Time remaining today",
  extension_today: "Extra time today",
  songs_today: "Songs today",
  blocked_today: "Blocked today",
  sleep_timer: "Sleep timer",
  next_schedule: "Next schedule",
  block_current_track: "Block this song",
  block_current_artist: "Block this artist",
};
const ENTITY_ORDER = Object.keys(ENTITY_LABELS);

const STYLES = `
:host {
  display: block; min-height: 100vh;
  background: var(--primary-background-color); color: var(--primary-text-color);
  font-family: var(--paper-font-body1_-_font-family, var(--ha-font-family-body, Roboto, sans-serif));
  --mm-good: var(--success-color, #43a047);
  --mm-warn: var(--warning-color, #ffa600);
  --mm-bad: var(--error-color, #db4437);
  --mm-info: var(--info-color, #039be5);
  --mm-radius: var(--ha-card-border-radius, 12px);
  --mm-tile: #141a24;
  --mm-tile-text: #f3f6fa;
}
* { box-sizing: border-box; }
button, input, select, textarea { font: inherit; color: inherit; }
.icon { width: 18px; height: 18px; fill: currentColor; flex: none; }

header { position: sticky; top: 0; z-index: 2; background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, var(--text-primary-color, #fff)); }
.bar { display: flex; align-items: center; height: 56px; padding: 0 12px; gap: 4px; }
.bar h1 { font-size: 20px; font-weight: 400; margin: 0 0 0 8px; }
nav { display: flex; gap: 4px; padding: 0 12px; overflow-x: auto; scrollbar-width: none; }
nav button { background: none; border: 0; padding: 12px 14px 10px; cursor: pointer; opacity: .75; border-bottom: 2px solid transparent; white-space: nowrap; font-size: 14px; }
nav button[aria-selected="true"] { opacity: 1; border-bottom-color: currentColor; }
@media (max-width: 420px) { nav { gap: 0; padding: 0 4px; } nav button { padding: 12px 10px 10px; } }
:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }

main { max-width: 1100px; margin: 0 auto; padding: 20px 16px 48px; }
main.wide { max-width: 1500px; }
.empty { max-width: 520px; margin: 48px auto; text-align: center; color: var(--secondary-text-color); line-height: 1.5; }
.empty h2 { color: var(--primary-text-color); font-weight: 500; }
.error { background: color-mix(in srgb, var(--mm-bad) 12%, transparent); border-left: 4px solid var(--mm-bad); padding: 12px 14px; border-radius: 8px; margin-bottom: 16px; }
.grid { display: grid; gap: 20px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); }
.stack { display: grid; gap: 20px; }
.card { background: var(--card-background-color, var(--ha-card-background, #fff)); border-radius: var(--mm-radius); box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color); overflow: hidden; }
.card-body { padding: 16px; display: grid; gap: 16px; }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.card-head h2, .card-head h3 { margin: 0; font-size: 17px; font-weight: 500; }
.muted { color: var(--secondary-text-color); font-size: 14px; }
small.muted { font-size: 13px; }

/* Speaker card */
.speaker-card { container: spk / inline-size; }
.seg.wide { display: grid; grid-template-columns: 1fr 1fr; width: 100%; max-width: 480px; }
.seg.wide button { text-align: center; }
.grid { align-items: start; }
.speaker-card.collapsed .tile-wrap { padding-bottom: 4px; }
.speaker-card.collapsed .tile-block { display: none; }
.expand { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; min-height: 44px;
  padding: 10px 16px; border: 0; border-top: 1px solid var(--divider-color); background: none; cursor: pointer;
  color: var(--secondary-text-color); font-size: 14px; text-align: left; }
.expand span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.expand:hover { background: color-mix(in srgb, var(--primary-color) 6%, transparent); }
.expand:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
.expand .icon { transition: transform .15s; }
.expand[aria-expanded="true"] .icon { transform: rotate(180deg); }
.spk-layout { display: grid; }
@container spk (min-width: 760px) {
  .spk-layout { grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); }
  .spk-layout > .col + .col { border-left: 1px solid var(--divider-color); }
}
.tile-wrap { padding: 16px 16px 0; }
.tile { position: relative; display: flex; gap: 14px; align-items: center; padding: 14px; border-radius: 14px; background: var(--mm-tile); color: var(--mm-tile-text); min-height: 132px; overflow: hidden; }
.tile .glow { position: absolute; inset: 0; opacity: .35; pointer-events: none; background: radial-gradient(120% 90% at 15% 0%, var(--mm-glow, #5c6bc0) 0%, transparent 60%); }
.tile.off { background: #0b0d10; } .tile.off .glow { opacity: 0; }
.tile.blocked .glow { --mm-glow: var(--mm-bad); opacity: .5; }
.tile.schedule .glow { --mm-glow: #26a69a; }
.art { position: relative; flex: none; width: 104px; height: 104px; border-radius: 10px; overflow: hidden; display: grid; place-items: center; background: rgba(255,255,255,.08); color: rgba(255,255,255,.55); }
.art img { width: 100%; height: 100%; object-fit: cover; display: block; }
.art .icon { width: 40px; height: 40px; }
.meta { position: relative; min-width: 0; display: grid; gap: 3px; flex: 1; }
.meta .top { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 12px; opacity: .85; }
.meta .spk-name { background: none; border: 0; padding: 0; cursor: pointer; color: inherit; font-size: 13px; text-decoration: underline; text-decoration-color: rgba(255,255,255,.3); text-underline-offset: 3px; }
.meta .title { font-size: 20px; font-weight: 500; line-height: 1.2; overflow-wrap: anywhere; }
.meta .sub { font-size: 13px; opacity: .78; overflow-wrap: anywhere; }
.tile .chip { color: var(--mm-tile-text); background: rgba(255,255,255,.1); }
.progress { display: grid; gap: 4px; padding: 10px 16px 0; }
.track { height: 4px; border-radius: 2px; background: var(--divider-color); overflow: hidden; }
.fill { height: 100%; background: var(--primary-text-color); opacity: .7; }
.times { display: flex; justify-content: space-between; font-size: 12px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
.controls { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.icon-btn { width: 42px; height: 42px; border-radius: 50%; border: 1px solid var(--divider-color); background: transparent; display: inline-grid; place-items: center; cursor: pointer; }
.icon-btn[data-primary] { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
.icon-btn:hover { background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
.icon-btn[data-primary]:hover { background: var(--primary-color); filter: brightness(1.08); }
.icon-btn:disabled { opacity: .45; cursor: default; }
.vol { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 180px; }
.vol-range { position: relative; flex: 1; display: grid; }
.vol input[type=range] { width: 100%; accent-color: var(--primary-color); }
.vol .cap { position: absolute; top: -2px; bottom: -2px; width: 2px; background: var(--mm-warn); pointer-events: none; }
.vol output { min-width: 3.2em; text-align: right; font-size: 13px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }

.chip { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; padding: 3px 10px; border-radius: 999px; background: color-mix(in srgb, var(--mm-tone) 16%, transparent); }
.chip::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--mm-tone); }
.tone-good { --mm-tone: var(--mm-good); } .tone-warn { --mm-tone: var(--mm-warn); }
.tone-bad { --mm-tone: var(--mm-bad); } .tone-info { --mm-tone: var(--mm-info); } .tone-muted { --mm-tone: var(--secondary-text-color); }

.time-line { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.time-line strong { font-size: 22px; font-weight: 500; }
.meter { height: 8px; border-radius: 4px; background: var(--divider-color); overflow: hidden; margin-top: 8px; }
.meter > div { height: 100%; background: var(--mm-tone, var(--primary-color)); border-radius: 4px; }
.facts { display: grid; grid-template-columns: auto 1fr; gap: 6px 16px; font-size: 14px; margin: 0; }
.facts dt { color: var(--secondary-text-color); } .facts dd { margin: 0; overflow-wrap: anywhere; }

.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.row > .label { width: 100%; font-size: 14px; color: var(--secondary-text-color); }
.btn { border: 1px solid var(--divider-color); background: transparent; border-radius: 8px; padding: 7px 12px; cursor: pointer; font-size: 14px; min-height: 36px; display: inline-flex; align-items: center; gap: 6px; }
.btn:hover { background: color-mix(in srgb, var(--primary-color) 8%, transparent); }
.btn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
.btn.danger { color: var(--mm-bad); border-color: color-mix(in srgb, var(--mm-bad) 45%, transparent); }
.btn.small { min-height: 30px; padding: 4px 9px; font-size: 13px; }
.btn.small .icon { width: 16px; height: 16px; }
.btn[disabled] { opacity: .5; cursor: default; }
.btn[aria-pressed="true"] { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
.seg { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 8px; overflow: hidden; }
.seg button { background: none; border: 0; padding: 7px 12px; cursor: pointer; font-size: 14px; min-height: 36px; }
.seg button + button { border-left: 1px solid var(--divider-color); }
.seg button[aria-pressed="true"] { background: var(--primary-color); color: var(--text-primary-color, #fff); }

.toggle { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 14px; }
.toggle small { display: block; color: var(--secondary-text-color); }
.switch { position: relative; width: 40px; height: 22px; flex: none; }
.switch input { opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; position: absolute; z-index: 1; }
.switch span { position: absolute; inset: 0; border-radius: 11px; background: var(--divider-color); transition: background .15s; }
.switch span::after { content: ""; position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: transform .15s; box-shadow: 0 1px 2px rgba(0,0,0,.3); }
.switch input:checked + span { background: var(--primary-color); }
.switch input:checked + span::after { transform: translateX(18px); }
.switch input:focus-visible + span { outline: 2px solid var(--primary-color); outline-offset: 2px; }

.panel-box { border: 1px solid var(--divider-color); border-radius: 10px; padding: 12px; display: grid; gap: 10px; }
.panel-box > .head { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 500; }
.panel-box > .head .icon { color: var(--secondary-text-color); }
.entity-links { display: flex; flex-wrap: wrap; gap: 6px; }
.entity-links button, .chip-btn { font-size: 13px; padding: 4px 10px; border-radius: 14px; border: 1px solid var(--divider-color); background: transparent; cursor: pointer; }
.entity-links button:hover, .chip-btn:hover { background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
.mini-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; font-size: 14px; }
.mini-list li { display: flex; justify-content: space-between; gap: 8px; }

.toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.picker { display: flex; flex-wrap: wrap; gap: 6px; }
.date-nav { display: flex; align-items: center; gap: 4px; }
.date-nav .btn { padding: 6px; min-width: 36px; justify-content: center; }
.date-nav h2 { font-size: 18px; font-weight: 500; margin: 0 8px; min-width: 9em; text-align: center; }

.tape { position: relative; height: 44px; border-radius: 8px; background: var(--secondary-background-color, var(--divider-color)); overflow: hidden; }
.tape .seg-bar { position: absolute; top: 0; bottom: 0; min-width: 2px; }
.tape .seg-bar.live { background-image: repeating-linear-gradient(135deg, transparent 0 6px, rgba(255,255,255,.25) 6px 12px); }
.tape .now-line { position: absolute; top: -2px; bottom: -2px; width: 2px; background: var(--primary-text-color); opacity: .6; }
.hours { position: relative; height: 18px; font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
.hours span { position: absolute; transform: translateX(-50%); }
.legend { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 14px; margin-top: 12px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; }

.log { list-style: none; margin: 0; padding: 0; }
.log li { display: grid; grid-template-columns: 72px 22px 1fr auto; gap: 10px; align-items: start; padding: 10px 0; border-top: 1px solid var(--divider-color); font-size: 14px; }
.log li:first-child { border-top: 0; }
.log time { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
.log .icon { margin-top: 1px; color: var(--secondary-text-color); }
.log .tone-bad .icon { color: var(--mm-bad); } .log .tone-warn .icon { color: var(--mm-warn); }
.log .acts { display: flex; gap: 4px; }
@media (max-width: 600px) { .log li { grid-template-columns: 60px 22px 1fr; } .log .acts { grid-column: 3; } }

.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 20px; }
.stat { padding: 14px 16px; }
.stat b { display: block; font-size: 24px; font-weight: 500; }
.stat span { color: var(--secondary-text-color); font-size: 14px; }
.chart { width: 100%; height: auto; display: block; }
.chart .day-bar { fill: var(--primary-color); }
.chart .day-bar.over { fill: var(--mm-warn); }
.chart .sched-bar { fill: #26a69a; }
.chart .hour-bar { fill: var(--mm-info); }
.chart .limit { fill: none; stroke: var(--primary-text-color); stroke-width: 1.5; stroke-dasharray: 4 3; opacity: .55; }
.chart .grid-line { stroke: var(--divider-color); }
.chart text { fill: var(--secondary-text-color); font-size: 11px; }
.legend i.limit-key { background: var(--primary-color); } .legend i.sched-key { background: #26a69a; }
.top-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; font-size: 14px; }
.top-list li { display: grid; grid-template-columns: minmax(0, 12em) 1fr 5.5em auto; gap: 10px; align-items: center; }
.top-list .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top-list .name small { display: block; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; }
.top-list .muted { text-align: right; }
.bar-track { height: 10px; border-radius: 5px; background: var(--divider-color); overflow: hidden; }
.bar-fill { height: 100%; background: var(--primary-color); border-radius: 5px; }
.top-grid { display: grid; gap: 20px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr)); margin-top: 20px; }
@media (max-width: 600px) { .top-list li { grid-template-columns: minmax(0, 1fr) 4.5em auto; } .top-list .bar-track { display: none; } }

/* Played music */
.search { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 220px; max-width: 420px; position: relative; }
.search .icon { position: absolute; left: 10px; color: var(--secondary-text-color); }
.search input { padding-left: 34px !important; width: 100%; }
.lib { width: 100%; border-collapse: collapse; font-size: 14px; }
.lib th { text-align: left; font-weight: 500; color: var(--secondary-text-color); font-size: 13px; padding: 8px 10px; border-bottom: 1px solid var(--divider-color); white-space: nowrap; }
.lib td { padding: 9px 10px; border-bottom: 1px solid var(--divider-color); vertical-align: middle; }
.lib tr:last-child td { border-bottom: 0; }
.lib td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.lib .song { font-weight: 500; overflow-wrap: anywhere; }
.lib .song small { display: block; font-weight: 400; color: var(--secondary-text-color); }
.lib .acts { display: flex; gap: 4px; justify-content: flex-end; flex-wrap: wrap; }
.lib tr.is-blocked .song { text-decoration: line-through; text-decoration-color: var(--mm-bad); }
.badge { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 8px; background: color-mix(in srgb, var(--mm-bad) 15%, transparent); color: var(--mm-bad); margin-left: 6px; text-decoration: none; vertical-align: 1px; }
@media (max-width: 700px) { .lib .hide-sm { display: none; } }

/* Schedules */
.sched { display: grid; grid-template-columns: auto 1fr auto; gap: 14px; align-items: start; }
.sched .when { font-size: 22px; font-weight: 500; font-variant-numeric: tabular-nums; line-height: 1.1; min-width: 5.5em; }
.sched .when small { display: block; font-size: 13px; font-weight: 400; color: var(--secondary-text-color); }
.sched h3 { margin: 0 0 4px; font-size: 16px; font-weight: 500; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.sched .what { font-size: 14px; }
.sched .acts { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }
.sched.disabled .when, .sched.disabled h3 { opacity: .5; }
@media (max-width: 640px) { .sched { grid-template-columns: 1fr; } .sched .acts { justify-content: flex-start; } }
.days { display: flex; flex-wrap: wrap; gap: 6px; }
.days label { display: inline-flex; }
.days input { position: absolute; opacity: 0; pointer-events: none; }
.days span { display: inline-grid; place-items: center; min-width: 46px; height: 34px; border-radius: 17px; border: 1px solid var(--divider-color); font-size: 13px; cursor: pointer; padding: 0 8px; }
.days input:checked + span { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
.days input:focus-visible + span { outline: 2px solid var(--primary-color); outline-offset: 2px; }

/* Forms */
form { display: grid; gap: 20px; }
.form-grid { display: grid; gap: 16px 20px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); }
.field { display: grid; gap: 6px; align-content: start; }
.field > label, .field > .label { font-size: 14px; font-weight: 500; }
.field small { color: var(--secondary-text-color); font-size: 13px; line-height: 1.4; }
input[type="number"], input[type="text"], input[type="time"], input[type="search"], select, textarea {
  font-size: 15px; padding: 9px 12px; border-radius: 8px; min-height: 42px;
  border: 1px solid var(--divider-color); background: var(--card-background-color, transparent); color: var(--primary-text-color);
}
textarea { min-height: 90px; resize: vertical; }
input[type="number"] { width: 130px; }
.inline { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.windows { display: grid; gap: 8px; }
.window { display: grid; grid-template-columns: auto auto 1fr auto; gap: 8px; align-items: center; }
.window input[type="text"] { min-width: 0; }
.form-actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.saved { color: var(--mm-good); font-size: 14px; }
.radio { display: flex; align-items: center; gap: 8px; font-size: 14px; min-height: 30px; }
input[type="checkbox"].check, input[type="radio"] { width: 18px; height: 18px; accent-color: var(--primary-color); }
.rules { display: grid; gap: 14px; }
.rule-group { display: grid; gap: 8px; }
.rule-group > .label { font-size: 14px; font-weight: 500; display: flex; justify-content: space-between; }
.rule-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.rule-chip { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; padding: 3px 4px 3px 10px; border-radius: 14px; background: color-mix(in srgb, var(--mm-bad) 12%, transparent); }
.rule-chip button { border: 0; background: none; cursor: pointer; display: inline-grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; padding: 0; }
.rule-chip button:hover { background: color-mix(in srgb, var(--mm-bad) 20%, transparent); }
.rule-chip .icon { width: 14px; height: 14px; }
.add-rule { display: flex; gap: 8px; flex-wrap: wrap; }
.add-rule select { min-width: 9em; }
.add-rule input { flex: 1; min-width: 180px; }
.people { display: grid; }
.person { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 10px 0; border-top: 1px solid var(--divider-color); font-size: 15px; }
.person:first-child { border-top: 0; }
.person .tag { font-size: 12px; color: var(--secondary-text-color); }
.speakers-pick { display: grid; gap: 6px; max-height: 220px; overflow: auto; padding: 4px 2px; }

@media (max-width: 600px) {
  main { padding: 12px 10px 40px; }
  .grid { grid-template-columns: 1fr; gap: 14px; }
  .window { grid-template-columns: 1fr 1fr auto; }
  .window input[type="text"] { grid-column: 1 / 3; grid-row: 2; }
  .art { width: 84px; height: 84px; }
  .date-nav h2 { min-width: 0; font-size: 16px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
`;

class MediaMgmtPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "dashboard";
    this._profiles = null;
    this._selected = null;
    this._activity = null;
    this._activityDate = null;
    this._range = 7;
    this._analytics = null;
    this._analyticsScope = null; // entry id or "all"
    this._library = null;
    this._libView = "songs";
    this._libSort = "last";
    this._libQuery = "";
    this._settings = null;
    this._draft = null;
    this._schedEdit = null;
    this._notes = {};
    this._error = null;
    this._busy = false;
    // Speakers opened on the dashboard. Collapsed (just the player) by default;
    // remembered on this device.
    this._expanded = new Set();
    try {
      this._expanded = new Set(JSON.parse(localStorage.getItem(EXPANDED_KEY) || "[]"));
    } catch (err) {
      /* storage unavailable: everything starts collapsed */
    }
  }

  _toggleExpanded(id) {
    if (this._expanded.has(id)) this._expanded.delete(id);
    else this._expanded.add(id);
    try {
      localStorage.setItem(EXPANDED_KEY, JSON.stringify([...this._expanded]));
    } catch (err) {
      /* not remembered, still works */
    }
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (first) this._start();
    else this._refreshTiles();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menu) this._menu.narrow = narrow;
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub()).catch(() => {});
      this._unsub = null;
    }
    clearInterval(this._timer);
    clearInterval(this._progressTimer);
    this._timer = this._progressTimer = null;
  }

  // ---- data ------------------------------------------------------------------

  _ws(msg) {
    return this._hass.callWS(msg);
  }

  get _profile() {
    return this._profiles?.find((p) => p.entry_id === this._selected) ?? null;
  }

  async _start() {
    try {
      this._me = await this._ws({ type: "media_mgmt/access/me" });
    } catch (err) {
      this._me = null;
    }
    this._renderShell();
    if (this._me && !this._me.allowed) {
      this._renderDenied();
      return;
    }
    await this._loadProfiles();
    this._subscribe();
  }

  _renderDenied() {
    const me = this._me;
    this.shadowRoot.getElementById("main").innerHTML = `<div class="empty" role="alert">
      <h2>You don't have access to Media Mgmt</h2>
      <p>Ask an admin to give you access. They can do it in Media Mgmt, under Access.</p>
      ${me.user_id ? `<p class="muted">Signed in as ${esc(me.name || "")}<br>User ID <code>${esc(me.user_id)}</code></p>` : ""}
    </div>`;
  }

  _subscribe() {
    if (this._unsub || !this._hass) return;
    this._unsub = this._hass.connection
      .subscribeMessage(() => this._scheduleRefresh(), { type: "media_mgmt/subscribe" })
      .catch((err) => {
        this._unsub = null;
        this._showError(err);
      });
    clearInterval(this._timer);
    this._timer = setInterval(() => this._scheduleRefresh(), 30000);
    clearInterval(this._progressTimer);
    this._progressTimer = setInterval(() => this._tickProgress(), 1000);
  }

  _scheduleRefresh() {
    if (this._refreshPending) return;
    this._refreshPending = true;
    setTimeout(async () => {
      this._refreshPending = false;
      await this._loadProfiles({ quiet: true });
      if (this._tab === "activity" && this._activity && this._activity.date === this._activity.today) {
        await this._loadActivity({ quiet: true });
      }
    }, 700);
  }

  // Forms keep what you're typing; live updates don't redraw them.
  _holdRender() {
    if (this._tab === "rules") return true;
    if (this._tab === "schedules" && this._schedEdit) return true;
    const el = this.shadowRoot.activeElement;
    return !!el && (el.tagName === "TEXTAREA" || el.tagName === "SELECT" || (el.tagName === "INPUT" && ["text", "number", "search", "time", "range"].includes(el.type)));
  }

  async _loadProfiles({ quiet = false } = {}) {
    try {
      const res = await this._ws({ type: "media_mgmt/profiles" });
      this._profiles = res.profiles;
      if (!this._selected || !this._profiles.some((p) => p.entry_id === this._selected)) {
        this._selected = this._profiles[0]?.entry_id ?? null;
      }
      if (!quiet) this._error = null;
    } catch (err) {
      if (!quiet) this._error = this._errorText(err);
    }
    if (quiet && this._holdRender()) {
      this._renderLater = true;
      return;
    }
    this._render();
  }

  async _loadActivity({ quiet = false } = {}) {
    if (!this._selected) return;
    try {
      this._activity = await this._ws({ type: "media_mgmt/activity", entry_id: this._selected, ...(this._activityDate ? { date: this._activityDate } : {}) });
      this._activityDate = this._activity.date;
      if (!quiet) this._error = null;
    } catch (err) {
      this._error = this._errorText(err);
    }
    if (quiet && this._holdRender()) return;
    this._render();
  }

  async _loadAnalytics() {
    const scope = this._analyticsScope || this._selected;
    try {
      this._analytics = await this._ws({ type: "media_mgmt/analytics", days: this._range, ...(scope === "all" ? {} : { entry_id: scope }) });
      this._analytics.scope = scope;
      this._error = null;
    } catch (err) {
      this._error = this._errorText(err);
    }
    this._render();
  }

  async _loadLibrary() {
    if (!this._selected) return;
    const req = { entry_id: this._selected, view: this._libView, sort: this._libSort, query: this._libQuery };
    try {
      const res = await this._ws({ type: "media_mgmt/history", ...req, limit: 300 });
      this._library = { ...res, ...req };
      this._error = null;
    } catch (err) {
      this._error = this._errorText(err);
    }
    this._render();
    if (this._focusSearch) {
      const el = this.shadowRoot.getElementById("lib-search");
      if (el) {
        el.focus();
        el.setSelectionRange(el.value.length, el.value.length);
      }
    }
  }

  async _loadSettings() {
    if (!this._selected) return;
    try {
      this._settings = await this._ws({ type: "media_mgmt/settings/get", entry_id: this._selected });
      this._settings.for = this._selected;
      this._draft = {
        ...this._settings,
        windows: this._parseWindows(this._settings.quiet_windows),
        filter: Object.fromEntries(Object.entries(this._settings.filter).map(([k, v]) => [k, [...v]])),
      };
      this._error = null;
    } catch (err) {
      this._error = this._errorText(err);
    }
    this._render();
  }

  async _action(entryId, action, extra = {}) {
    try {
      const res = await this._ws({ type: "media_mgmt/action", entry_id: entryId, action, ...extra });
      const index = this._profiles.findIndex((p) => p.entry_id === entryId);
      if (index >= 0) this._profiles[index] = res.profile;
      this._error = null;
    } catch (err) {
      this._error = this._errorText(err);
    }
    this._render();
  }

  async _block(entryId, kind, value, add = true) {
    try {
      await this._ws({ type: "media_mgmt/filter/update", entry_id: entryId, kind, value, add });
      this._notes.block = `${add ? "Blocked" : "Unblocked"} ${KIND_LABELS[kind].toLowerCase()} “${value}”`;
      this._error = null;
    } catch (err) {
      this._error = this._errorText(err);
    }
    await this._loadProfiles({ quiet: true });
    if (this._tab === "library") await this._loadLibrary();
    else if (this._tab === "analytics") await this._loadAnalytics();
    else if (this._tab === "rules") await this._loadSettings();
    else this._render();
  }

  async _callService(domain, service, data) {
    try {
      await this._hass.callService(domain, service, data);
      this._error = null;
    } catch (err) {
      this._error = this._errorText(err);
      this._render();
    }
  }

  _errorText(err) {
    if (err?.code === "unauthorized") return "You don't have access to Media Mgmt. An admin can give you access under Access.";
    return err?.message || String(err);
  }

  _showError(err) {
    this._error = this._errorText(err);
    this._render();
  }

  _parseWindows(text) {
    return (text || "")
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [times, ...label] = part.split(" ");
        const [start, end] = times.split("-");
        return { start, end, label: label.join(" ") };
      });
  }

  // ---- rendering ----------------------------------------------------------------

  _tabs() {
    if (this._me && !this._me.allowed) return [];
    return this._me?.is_admin ? [...TABS, { id: "speakers", label: "Speakers" }, { id: "access", label: "Access" }] : TABS;
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <header>
        <div class="bar"><span id="menu"></span><h1>Media Mgmt</h1></div>
        <nav role="tablist" aria-label="Media Mgmt sections">
          ${this._tabs().map((t) => `<button role="tab" data-tab="${t.id}" aria-selected="${t.id === this._tab}">${t.label}</button>`).join("")}
        </nav>
      </header>
      <main id="main" aria-live="polite"></main>`;
    const menu = document.createElement("ha-menu-button");
    menu.hass = this._hass;
    menu.narrow = this._narrow;
    this._menu = menu;
    this.shadowRoot.getElementById("menu").appendChild(menu);

    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
    this.shadowRoot.addEventListener("input", (ev) => this._onInput(ev));
    this.shadowRoot.addEventListener("submit", (ev) => this._onSubmit(ev));
    this.shadowRoot.addEventListener("focusout", () => {
      setTimeout(() => {
        if (this._renderLater && !this._holdRender()) {
          this._renderLater = false;
          this._render();
        }
      }, 0);
    });
  }

  _render() {
    const main = this.shadowRoot.getElementById("main");
    if (!main) return;
    this.shadowRoot.querySelectorAll("nav button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === this._tab)));
    let body;
    if (this._tab === "access") body = this._renderAccess();
    else if (this._tab === "speakers") body = this._renderSpeakers();
    else if (this._profiles === null) body = this._error ? "" : `<p class="empty">Loading your speakers…</p>`;
    else if (!this._profiles.length)
      body = this._me?.is_admin
        ? `<div class="empty"><h2>No speakers yet</h2><p>Pick the speakers to manage, and set everything else up here.</p><p><button class="btn primary" data-tab="speakers">${icon("plus")} Add a speaker</button></p></div>`
        : `<div class="empty"><h2>No speakers yet</h2><p>Ask an admin to add a speaker in Media Mgmt, under Speakers.</p></div>`;
    else
      body = {
        dashboard: () => this._renderDashboard(),
        activity: () => this._renderActivity(),
        analytics: () => this._renderAnalytics(),
        library: () => this._renderLibrary(),
        schedules: () => this._renderSchedules(),
        rules: () => this._renderRules(),
      }[this._tab]();
    const error = this._error ? `<div class="error" role="alert">${esc(this._error)}</div>` : "";
    main.classList.toggle("wide", this._tab === "dashboard");
    main.innerHTML = error + body;
    this._npStates = {};
  }

  _picker({ all = false } = {}) {
    if (this._profiles.length < 2 && !all) return `<div></div>`;
    const current = all ? this._analyticsScope || this._selected : this._selected;
    const buttons = this._profiles.map((p) => `<button class="btn" data-pick="${p.entry_id}" aria-pressed="${p.entry_id === current}">${esc(p.name)}</button>`);
    if (all && this._profiles.length > 1) buttons.push(`<button class="btn" data-pick="all" aria-pressed="${current === "all"}">All speakers</button>`);
    return `<div class="picker" role="group" aria-label="Speaker">${buttons.join("")}</div>`;
  }

  _note(key) {
    return this._notes[key] ? `<span class="saved" role="status">${esc(this._notes[key])}</span>` : "";
  }

  // Dashboard ------------------------------------------------------------------------

  _renderDashboard() {
    const note = this._notes.block ? `<div class="toolbar"><span class="saved" role="status">${esc(this._notes.block)}</span></div>` : "";
    return `${note}<div class="grid">${this._profiles.map((p) => this._renderSpeaker(p)).join("")}</div>`;
  }

  _renderSpeaker(p) {
    const id = p.entry_id;
    const state = stateInfo(p);
    const limit = p.budget_minutes > 0 ? p.budget_minutes + p.extension_minutes : 0;
    const usedMin = minutes(p.used_seconds);
    const pct = limit ? Math.min(100, (usedMin / limit) * 100) : 0;
    const timeLine = limit
      ? `<div class="time-line"><span><strong>${duration(p.used_seconds)}</strong> <span class="muted">of ${duration(limit * 60)}</span></span><span class="muted">${p.remaining_seconds > 0 ? `${duration(p.remaining_seconds)} left` : "No time left"}</span></div>
         <div class="meter" role="progressbar" aria-valuemin="0" aria-valuemax="${limit}" aria-valuenow="${usedMin}" aria-label="Listening time used"><div class="tone-${state.tone === "bad" ? "bad" : state.tone === "warn" ? "warn" : "info"}" style="width:${pct}%"></div></div>`
      : `<div class="time-line"><span><strong>${duration(p.used_seconds)}</strong> <span class="muted">listened today</span></span><span class="muted">No daily limit</span></div>`;
    const schedNote = p.schedule_seconds ? `<small class="muted">Plus ${duration(p.schedule_seconds)} from schedules, which don't count toward the limit.</small>` : "";
    const adultOn = p.state === "adult_mode" || !!p.adult_mode_until;
    const nextSched = (p.schedules || []).filter((s) => s.enabled && s.next_run).sort((a, b) => a.next_run.localeCompare(b.next_run))[0];
    const active = (p.schedules || []).find((s) => s.active);
    // A volume limit on right now (limits that only limit; music schedules show above).
    const limiting = (p.schedules || []).find((s) => s.play_kind === "none" && s.name === p.volume_limit_schedule);
    const open = this._expanded.has(id);
    // Collapsed: just the player, with a one-line summary on the button that opens the rest.
    const summary = [
      limit ? `${duration(p.used_seconds)} of ${duration(limit * 60)}` : `${duration(p.used_seconds)} today`,
      active ? `${active.name} until ${hhmmLabel(active.stop)}` : limiting ? `Volume up to ${limiting.volume_limit}% until ${hhmmLabel(limiting.stop)}` : p.sleep_until ? `Sleep timer ${timeOf(p.sleep_until)}` : "",
    ].filter(Boolean).join(" · ");
    const toggle = `<button class="expand" data-expand="${id}" aria-expanded="${open}" aria-controls="more-${id}">
        <span>${open ? "Show less" : esc(summary)}</span>${icon("chevron-down")}</button>`;
    if (!open) {
      return `
      <section class="card speaker-card collapsed" aria-label="${esc(p.name)}">
        <div class="tile-wrap" id="np-${id}">${this._tile(p)}</div>
        ${toggle}
      </section>`;
    }

    return `
      <section class="card speaker-card" aria-label="${esc(p.name)}">
        <div class="spk-layout" id="more-${id}">
          <div class="col">
            <div class="tile-wrap" id="np-${id}">${this._tile(p)}</div>
            <div class="card-body">
              <div>${timeLine}${schedNote}</div>
              ${this._sleepBox(p)}
              <div class="panel-box">
                <div class="head">${icon("calendar")} Schedules</div>
                ${active ? `<div class="chip tone-info">${esc(active.name)} is playing until ${esc(hhmmLabel(active.stop))}${active.volume_limit != null ? `, up to ${active.volume_limit}% volume` : ""}</div>` : ""}
                ${limiting ? `<div class="chip tone-info">${esc(limiting.name)}: volume up to ${limiting.volume_limit}% until ${esc(hhmmLabel(limiting.stop))}</div>` : ""}
                ${nextSched
                  ? `<div class="row"><span>Next: <strong>${esc(nextSched.name)}</strong>, ${esc(whenLabel(nextSched.next_run))}</span>
                      ${nextSched.play_kind !== "none" ? `<button class="btn small" data-run="${esc(nextSched.id)}" data-id="${id}">${icon("play")} Play now</button>` : ""}</div>`
                  : `<span class="muted">No schedules yet.</span>`}
                <div><button class="btn small" data-goto="schedules" data-id="${id}">${icon("calendar")} ${p.schedules?.length ? "Manage schedules" : "Add a schedule"}</button></div>
              </div>
            </div>
          </div>
          <div class="col card-body">
            <dl class="facts">
              <dt>Songs today</dt><dd>${p.plays}</dd>
              <dt>Blocked today</dt><dd>${p.blocked_count}${p.last_blocked ? `, last ${esc(p.last_blocked)}${p.last_blocked_at ? ` at ${timeOf(p.last_blocked_at)}` : ""}` : ""}</dd>
              <dt>Extra time</dt><dd>${p.extension_minutes ? `${p.extension_minutes > 0 ? "+" : ""}${p.extension_minutes} min` : "None"}</dd>
              <dt>Volume cap</dt><dd>${capLabel(p)}</dd>
            </dl>
            ${p.top_artists?.length ? `<div><div class="muted" style="margin-bottom:6px">Top artists today</div><ul class="mini-list">${p.top_artists
              .map((a) => `<li><span>${esc(a.name)}</span><span class="muted">${duration(a.seconds)}</span></li>`)
              .join("")}</ul></div>` : ""}
            <div class="row">
              <span class="label">Extra time</span>
              <button class="btn" data-act="grant_extension" data-id="${id}" data-minutes="-15">−15 min</button>
              <button class="btn" data-act="grant_extension" data-id="${id}" data-minutes="15">+15 min</button>
              <button class="btn" data-act="grant_extension" data-id="${id}" data-minutes="30">+30 min</button>
              <button class="btn" data-act="grant_extension" data-id="${id}" data-minutes="60">+1 h</button>
            </div>
            <div class="row">
              <span class="label">Mode</span>
              <div class="seg" role="group" aria-label="Mode">
                ${MODES.map((m) => `<button data-act="set_mode" data-id="${id}" data-mode="${m.id}" aria-pressed="${p.mode === m.id}">${m.label}</button>`).join("")}
              </div>
            </div>
            <label class="toggle"><span>Music filter<small>${this._filterSummary(p)}</small></span>
              <span class="switch"><input type="checkbox" data-toggle="set_music_filter" data-id="${id}" ${p.music_filter ? "checked" : ""}><span></span></span></label>
            <label class="toggle"><span>Adult mode<small>${adultOn && p.adult_mode_until ? `Rules lifted until ${timeOf(p.adult_mode_until)}` : `Lift every rule for ${duration(p.adult_mode_duration * 60)}`}</small></span>
              <span class="switch"><input type="checkbox" data-toggle="set_adult_mode" data-id="${id}" ${adultOn ? "checked" : ""}><span></span></span></label>
            <div class="row">
              ${p.force_block
                ? `<button class="btn primary" data-act="unblock" data-id="${id}">Unblock</button>`
                : `<button class="btn danger" data-act="force_block" data-id="${id}">${icon("stop")} Stop music now</button>`}
              <button class="btn" data-act="reset_usage" data-id="${id}" data-confirm="Reset today's listening time, extra time and block for ${esc(p.name)}?">Reset today</button>
            </div>
            ${this._entityLinks(p)}
          </div>
        </div>
        ${toggle}
      </section>`;
  }

  _filterSummary(p) {
    const f = p.filter || {};
    const parts = Object.entries(f)
      .filter(([, v]) => v.length)
      .map(([k, v]) => `${v.length} ${(v.length === 1 ? KIND_LABELS[k] : KIND_PLURAL[k]).toLowerCase()}`);
    return parts.length ? `Blocking ${parts.join(", ")}` : "Nothing blocked yet";
  }

  _tile(p) {
    const st = this._hass?.states?.[p.entity_id];
    this._npStates = this._npStates || {};
    this._npStates[p.entity_id] = st;
    const attrs = st?.attributes || {};
    const s = st?.state;
    const unavailable = !st || s === "unavailable" || s === "unknown";
    const off = !unavailable && (s === "off" || s === "standby");
    const media = p.media;
    const id = p.entry_id;
    const chip = stateInfo(p);
    const blocked = p.blocked_by;
    let title;
    let sub = "";
    if (unavailable) title = "Can't reach the speaker";
    else if (off) title = "Off";
    else if (attrs.media_title) {
      title = attrs.media_title;
      sub = [attrs.media_artist, attrs.media_album_name].filter(Boolean).join(" · ");
    } else title = { idle: "Nothing playing", paused: "Paused", on: "On" }[s] || "Nothing playing";
    const source = attrs.app_name || attrs.source;
    const stateLabel = { playing: "Playing", paused: "Paused", idle: "Idle", buffering: "Loading" }[s];
    const pic = !unavailable && !off && attrs.entity_picture;
    const art = pic ? `<img src="${esc(this._hass.hassUrl ? this._hass.hassUrl(pic) : pic)}" alt="" loading="lazy" onerror="this.remove()">` : icon("note");
    const cls = ["tile", unavailable || off ? "off" : "", p.state === "enforcing" || blocked ? "blocked" : "", p.state === "schedule" ? "schedule" : ""].join(" ");

    const dur = Number(attrs.media_duration || 0);
    const progress = !unavailable && !off && dur > 0
      ? `<div class="progress" data-duration="${dur}" data-position="${Number(attrs.media_position || 0)}" data-updated="${esc(attrs.media_position_updated_at || "")}" data-playing="${s === "playing" ? 1 : 0}">
          <div class="track"><div class="fill" style="width:${Math.min(100, (Number(attrs.media_position || 0) / dur) * 100)}%"></div></div>
          <div class="times"><span class="elapsed">${clock(Number(attrs.media_position || 0))}</span><span>${clock(dur)}</span></div>
        </div>`
      : "";

    const caps = p.capabilities || {};
    const eid = esc(p.entity_id);
    const btn = (svc, ico, label, extra = "") => `<button class="icon-btn" data-media="${svc}" data-eid="${eid}" aria-label="${label}" title="${label}" ${extra}>${icon(ico)}</button>`;
    const playing = s === "playing";
    const controls = !unavailable
      ? [
          caps.previous ? btn("media_previous_track", "prev", "Previous") : "",
          (playing ? caps.pause : caps.play) ? btn("media_play_pause", playing ? "pause" : "play", playing ? "Pause" : "Play", 'data-primary="1"') : "",
          caps.next ? btn("media_next_track", "next", "Next") : "",
        ].join("")
      : "";
    const vol = attrs.volume_level != null && caps.volume
      ? `<div class="vol">${icon("volume")}<div class="vol-range">
          <input type="range" min="0" max="100" step="1" value="${Math.round(attrs.volume_level * 100)}" data-volume="${eid}" aria-label="Volume">
          ${capOf(p) < 100 ? `<span class="cap" style="left:calc(${capOf(p)}% - 1px)" title="${esc(capLabel(p))}"></span>` : ""}
        </div><output>${Math.round(attrs.volume_level * 100)}%</output></div>`
      : "";
    const blockButtons = media
      ? `<div class="row tile-block">
          ${blocked ? `<span class="chip tone-bad">Blocked: ${esc(KIND_LABELS[blocked.kind])} “${esc(blocked.rule)}”</span>` : ""}
          <button class="btn small" data-block="track" data-value="${esc(trackEntry(media.title, media.artist))}" data-id="${id}">${icon("block")} Block song</button>
          ${media.artist ? `<button class="btn small" data-block="artist" data-value="${esc(media.artist)}" data-id="${id}">${icon("block")} Block ${esc(media.artist)}</button>` : ""}
        </div>`
      : "";
    return `
      <div class="${cls}">
        <div class="glow"></div>
        <div class="art">${art}</div>
        <div class="meta">
          <div class="top"><button class="spk-name" data-more-info="${eid}">${esc(p.name)}</button>${stateLabel ? `<span>${stateLabel}</span>` : ""}${source ? `<span>· ${esc(source)}</span>` : ""}</div>
          <div class="title">${esc(title)}</div>
          ${sub ? `<div class="sub">${esc(sub)}</div>` : ""}
          <div><span class="chip tone-${chip.tone}">${esc(chip.text)}</span></div>
        </div>
      </div>
      ${progress}
      <div class="card-body" style="padding:12px 0 0">
        ${controls || vol ? `<div class="controls">${controls}${vol}</div>` : ""}
        ${blockButtons}
      </div>`;
  }

  _sleepBox(p) {
    const id = p.entry_id;
    const fade = this._notes[`fade-${id}`] ?? true;
    if (p.sleep_until) {
      return `<div class="panel-box"><div class="head">${icon("sleep")} Sleep timer</div>
        <div class="row"><span>Music stops at <strong>${timeOf(p.sleep_until)}</strong>${p.sleep_fade ? `, fading out over the last ${p.sleep_fade} min` : ""}.</span>
        <button class="btn small" data-act="cancel_sleep_timer" data-id="${id}">Cancel</button></div></div>`;
    }
    return `<div class="panel-box"><div class="head">${icon("sleep")} Sleep timer</div>
      <div class="row">
        ${SLEEP_PRESETS.map((m) => `<button class="btn small" data-sleep="${m}" data-id="${id}">${m < 60 ? `${m} min` : "1 h"}</button>`).join("")}
        <label class="radio"><input type="checkbox" class="check" data-fade="${id}" ${fade ? "checked" : ""}> Fade out</label>
      </div></div>`;
  }

  _entityLinks(p) {
    const own = (p.entities || []).filter((e) => ENTITY_LABELS[e.key]).sort((a, b) => ENTITY_ORDER.indexOf(a.key) - ENTITY_ORDER.indexOf(b.key));
    const links = [{ entity_id: p.entity_id, label: "Speaker" }, ...own.map((e) => ({ entity_id: e.entity_id, label: ENTITY_LABELS[e.key] }))];
    return `<div><div class="muted" style="margin-bottom:6px">Entities</div><div class="entity-links">${links
      .map((l) => `<button data-more-info="${esc(l.entity_id)}" title="${esc(l.entity_id)}">${esc(l.label)}</button>`)
      .join("")}</div></div>`;
  }

  // Redraw just the "now playing" tile when the speaker's state changes.
  _refreshTiles() {
    if (this._tab !== "dashboard" || !this._profiles) return;
    this._npStates = this._npStates || {};
    for (const p of this._profiles) {
      const st = this._hass.states[p.entity_id];
      if (st === this._npStates[p.entity_id]) continue;
      const node = this.shadowRoot.getElementById(`np-${p.entry_id}`);
      const focused = node?.contains(this.shadowRoot.activeElement);
      if (node && !focused) node.innerHTML = this._tile(p);
    }
  }

  _tickProgress() {
    this.shadowRoot.querySelectorAll(".progress[data-duration]").forEach((el) => {
      const dur = Number(el.dataset.duration);
      let pos = Number(el.dataset.position);
      if (el.dataset.playing === "1" && el.dataset.updated) pos += (Date.now() - new Date(el.dataset.updated).getTime()) / 1000;
      pos = Math.max(0, Math.min(dur, pos));
      const fill = el.querySelector(".fill");
      const elapsed = el.querySelector(".elapsed");
      if (fill) fill.style.width = `${(pos / dur) * 100}%`;
      if (elapsed) elapsed.textContent = clock(pos);
    });
  }

  // Activity -------------------------------------------------------------------------

  _renderActivity() {
    const a = this._activity;
    if (!a || a.entry_id !== this._selected) {
      if (!this._loadingActivity) {
        this._loadingActivity = true;
        this._loadActivity().finally(() => (this._loadingActivity = false));
      }
      return `${this._activityToolbar(null)}<p class="empty">Loading activity…</p>`;
    }
    const dayStart = new Date(`${a.date}T00:00:00`).getTime();
    const pos = (iso) => Math.max(0, Math.min(100, ((new Date(iso).getTime() - dayStart) / 86400000) * 100));
    const byArtist = {};
    for (const s of a.segments) byArtist[s.artist ?? "Unknown artist"] = (byArtist[s.artist ?? "Unknown artist"] || 0) + s.seconds;
    const ranked = Object.entries(byArtist).sort((x, y) => y[1] - x[1]);
    const colour = {};
    ranked.forEach(([name], i) => (colour[name] = COLOURS[Math.min(i, COLOURS.length - 1)]));
    const bars = a.segments
      .map((s) => {
        const left = pos(s.start);
        const width = Math.max(0.3, pos(s.end) - left);
        const who = s.artist ?? "Unknown artist";
        return `<div class="seg-bar${s.live ? " live" : ""}" style="left:${left}%;width:${width}%;background-color:${colour[who]}" title="${esc(s.title ? `${s.title} by ${who}` : who)}: ${timeOf(s.start)} to ${timeOf(s.end)}"></div>`;
      })
      .join("");
    const isToday = a.date === a.today;
    const nowLine = isToday ? `<div class="now-line" style="left:${pos(new Date().toISOString())}%"></div>` : "";
    const hours = [0, 6, 12, 18]
      .map((h) => `<span style="left:${(h / 24) * 100}%;${h === 0 ? "transform:none" : ""}">${new Date(dayStart + h * 3600000).toLocaleTimeString([], { hour: "numeric" })}</span>`)
      .join("");
    const legend = ranked.filter(([, secs]) => secs >= 30).map(([name, secs]) => `<span><i style="background:${colour[name]}"></i>${esc(name)}: ${duration(secs)}</span>`).join("");
    const id = this._selected;
    const events = a.events.length
      ? `<ul class="log">${a.events
          .map((e) => {
            const d = describeEvent(e);
            const acts = d.song && e.title
              ? `<span class="acts"><button class="btn small" data-block="track" data-value="${esc(trackEntry(e.title, e.artist))}" data-id="${id}" title="Block this song">${icon("block")} Song</button>${e.artist ? `<button class="btn small" data-block="artist" data-value="${esc(e.artist)}" data-id="${id}" title="Block ${esc(e.artist)}">${icon("block")} Artist</button>` : ""}</span>`
              : "<span></span>";
            return `<li class="${d.tone ? `tone-${d.tone}` : ""}"><time datetime="${e.t}">${timeOf(e.t)}</time>${icon(d.icon)}<span>${esc(d.text)}</span>${e.type === "play" ? acts : "<span></span>"}</li>`;
          })
          .join("")}</ul>`
      : `<p class="muted">Nothing happened on this speaker ${isToday ? "yet today" : "this day"}.</p>`;
    const t = a.totals;
    return `${this._activityToolbar(a)}
      <section class="card"><div class="card-body">
        <div class="time-line"><span><strong>${duration(a.listening_seconds)}</strong> <span class="muted">of music</span></span>
          ${t ? `<span class="muted">${t.plays} song${t.plays === 1 ? "" : "s"}, ${t.blocked} blocked</span>` : ""}</div>
        <div>
          <div class="tape" role="img" aria-label="When music played, by artist">${bars}${nowLine}</div>
          <div class="hours">${hours}</div>
          ${legend ? `<div class="legend">${legend}</div>` : ""}
        </div>
        ${this._notes.block ? `<div>${this._note("block")}</div>` : ""}
      </div></section>
      <section class="card" style="margin-top:20px"><div class="card-body">${events}</div></section>`;
  }

  _activityToolbar(a) {
    const date = a?.date;
    const today = a?.today;
    const canBack = a && (!a.first_date || date > a.first_date);
    const canForward = a && date < today;
    return `<div class="toolbar">${this._picker()}
      <div class="date-nav">
        <button class="btn" data-day="-1" aria-label="Previous day" ${canBack ? "" : "disabled"}>${icon("left")}</button>
        <h2>${a ? esc(dayLabel(date, today)) : ""}</h2>
        <button class="btn" data-day="1" aria-label="Next day" ${canForward ? "" : "disabled"}>${icon("right")}</button>
        ${a && date !== today ? `<button class="btn" data-day="today">Today</button>` : ""}
      </div></div>`;
  }

  // Analytics ------------------------------------------------------------------------

  _renderAnalytics() {
    const scope = this._analyticsScope || this._selected;
    const data = this._analytics;
    if (!data || data.scope !== scope || data.range !== this._range) {
      if (!this._loadingAnalytics) {
        this._loadingAnalytics = true;
        this._loadAnalytics().finally(() => (this._loadingAnalytics = false));
      }
      return `${this._analyticsToolbar()}<p class="empty">Loading analytics…</p>`;
    }
    const s = data.summary;
    const one = scope !== "all";
    const stats = `<div class="stats">
      <div class="card stat"><b>${duration(s.total_seconds)}</b><span>Music played</span></div>
      <div class="card stat"><b>${duration(s.average_seconds)}</b><span>Daily average</span></div>
      <div class="card stat"><b>${s.plays}</b><span>Songs played</span></div>
      <div class="card stat"><b>${s.blocked}</b><span>Blocked songs</span></div>
      ${one ? `<div class="card stat"><b>${s.days_over_limit}</b><span>Days the limit was reached</span></div>` : ""}
      ${s.schedule_seconds ? `<div class="card stat"><b>${duration(s.schedule_seconds)}</b><span>From schedules</span></div>` : ""}
    </div>`;
    const note = s.recorded_days < data.days.length
      ? `<p class="muted">Media Mgmt has ${s.recorded_days} day${s.recorded_days === 1 ? "" : "s"} of history so far. Days before that show as empty.</p>`
      : "";
    const speakers = !one && data.speakers.length > 1
      ? this._topCard("By speaker", data.speakers.map((x) => ({ name: x.name, seconds: x.seconds })), { kind: null })
      : "";
    return `${this._analyticsToolbar()}${stats}
      <section class="card"><div class="card-body">
        <div><strong>Music per day</strong><div class="muted">${one ? "The dashed line is the daily limit, including extra time. " : ""}Schedules don't count toward the limit.</div></div>
        ${this._dayChart(data.days, one)}
        <div class="legend"><span><i class="limit-key"></i>Counts toward the limit</span><span><i class="sched-key"></i>Schedules</span></div>
        ${note}
      </div></section>
      <section class="card" style="margin-top:20px"><div class="card-body">
        <div><strong>When music plays</strong><div class="muted">Total by hour of the day, over these ${this._range} days.</div></div>
        ${this._hourChart(s.hours)}
      </div></section>
      ${this._notes.block ? `<div style="margin-top:12px">${this._note("block")}</div>` : ""}
      <div class="top-grid">
        ${this._topCard("Top artists", s.top_artists.map((x) => ({ name: x.artist, seconds: x.seconds, blocked: x.blocked, value: x.artist })), { kind: one ? "artist" : null })}
        ${this._topCard("Top songs", s.top_tracks.map((x) => { const t = songOf(x.key); return { name: t.title, sub: t.artist, seconds: x.seconds, blocked: x.blocked, value: x.key }; }), { kind: one ? "track" : null })}
        ${this._topCard("Top albums", s.top_albums.map((x) => ({ name: x.album, seconds: x.seconds, value: x.album })), { kind: one ? "album" : null })}
        ${this._topCard("Apps and sources", s.top_sources.map((x) => ({ name: x.source, seconds: x.seconds, value: x.source })), { kind: one ? "source" : null })}
        ${speakers}
      </div>`;
  }

  _topCard(title, rows, { kind }) {
    const max = Math.max(1, ...rows.map((r) => r.seconds));
    const id = this._analyticsScope && this._analyticsScope !== "all" ? this._analyticsScope : this._selected;
    const list = rows.length
      ? `<ul class="top-list">${rows
          .map((r) => {
            const action = kind
              ? r.blocked
                ? `<button class="btn small" data-unblock="${esc(r.blocked.kind)}" data-value="${esc(r.blocked.rule)}" data-id="${id}">Unblock</button>`
                : `<button class="btn small" data-block="${kind}" data-value="${esc(r.value)}" data-id="${id}" title="Block ${esc(r.name)}">${icon("block")}</button>`
              : "<span></span>";
            return `<li><span class="name" title="${esc(r.name)}">${esc(r.name)}${r.blocked ? `<span class="badge">Blocked</span>` : ""}${r.sub ? `<small>${esc(r.sub)}</small>` : ""}</span><div class="bar-track"><div class="bar-fill" style="width:${(r.seconds / max) * 100}%"></div></div><span class="muted">${duration(r.seconds)}</span>${action}</li>`;
          })
          .join("")}</ul>`
      : `<p class="muted">Nothing in this range yet.</p>`;
    return `<section class="card"><div class="card-body"><strong>${esc(title)}</strong>${list}</div></section>`;
  }

  _analyticsToolbar() {
    return `<div class="toolbar">${this._picker({ all: true })}
      <div class="seg" role="group" aria-label="Range">
        ${RANGES.map((r) => `<button data-range="${r}" aria-pressed="${this._range === r}">${r} days</button>`).join("")}
      </div></div>`;
  }

  _chartWidth() {
    const main = this.shadowRoot.getElementById("main");
    return Math.max(280, Math.min(1060, (main?.clientWidth || 720) - 64));
  }

  _dayChart(days, showLimit) {
    const W = this._chartWidth();
    const H = 220, padL = 40, padB = 26, padT = 10, padR = 8;
    const used = days.map((d) => minutes(d.used_seconds));
    const sched = days.map((d) => minutes(d.schedule_seconds));
    const limits = days.map((d) => (showLimit && d.budget_minutes ? d.budget_minutes + d.extension_minutes : 0));
    const max = Math.max(60, ...used.map((u, i) => u + sched[i]), ...limits);
    const step = max > 300 ? 120 : max > 120 ? 60 : 30;
    const top = Math.ceil(max / step) * step;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const bw = plotW / days.length;
    const y = (v) => padT + plotH - (v / top) * plotH;
    let grid = "";
    for (let v = 0; v <= top; v += step) grid += `<line class="grid-line" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/><text x="${padL - 6}" y="${y(v) + 4}" text-anchor="end">${v >= 60 ? `${v / 60}h` : `${v}m`}</text>`;
    const bars = days
      .map((d, i) => {
        const x = padL + i * bw + bw * 0.15;
        const h1 = used[i] ? Math.max(2, (used[i] / top) * plotH) : 0;
        const h2 = sched[i] ? Math.max(2, (sched[i] / top) * plotH) : 0;
        const over = limits[i] && used[i] >= limits[i];
        const tip = `${d.date}: ${duration(d.used_seconds)}${sched[i] ? ` + ${duration(d.schedule_seconds)} from schedules` : ""}${limits[i] ? `, limit ${duration(limits[i] * 60)}` : ""}`;
        return `<g><title>${esc(tip)}</title><rect class="day-bar${over ? " over" : ""}" x="${x}" y="${padT + plotH - h1}" width="${bw * 0.7}" height="${h1}" rx="2"/><rect class="sched-bar" x="${x}" y="${padT + plotH - h1 - h2}" width="${bw * 0.7}" height="${h2}" rx="2"/></g>`;
      })
      .join("");
    let limitPath = "";
    days.forEach((d, i) => {
      if (!limits[i]) return;
      const x1 = padL + i * bw;
      limitPath += `M${x1} ${y(limits[i])}H${x1 + bw}`;
    });
    const labelWidth = days.length <= 7 ? 36 : 56;
    const every = Math.max(1, Math.ceil(days.length / Math.max(4, Math.floor(plotW / labelWidth))));
    const labels = days
      .map((d, i) => {
        if ((days.length - 1 - i) % every) return "";
        const date = new Date(`${d.date}T12:00:00`);
        const text = days.length <= 7 ? date.toLocaleDateString([], { weekday: "short" }) : date.toLocaleDateString([], { month: "short", day: "numeric" });
        return `<text x="${padL + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${text}</text>`;
      })
      .join("");
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Music per day">${grid}${bars}<path class="limit" d="${limitPath}"/>${labels}</svg>`;
  }

  _hourChart(hours) {
    const W = this._chartWidth();
    const H = 160, padL = 40, padB = 24, padT = 8, padR = 8;
    const vals = hours.map((s) => minutes(s));
    const max = Math.max(10, ...vals);
    const step = max > 240 ? 120 : max > 60 ? 60 : max > 20 ? 15 : 5;
    const top = Math.ceil(max / step) * step;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const bw = plotW / 24;
    const y = (v) => padT + plotH - (v / top) * plotH;
    let grid = "";
    for (let v = 0; v <= top; v += step) grid += `<line class="grid-line" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/><text x="${padL - 6}" y="${y(v) + 4}" text-anchor="end">${v >= 60 ? `${v / 60}h` : `${v}m`}</text>`;
    const bars = vals
      .map((v, h) => {
        const hh = v ? Math.max(2, (v / top) * plotH) : 0;
        const label = new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });
        return `<rect class="hour-bar" x="${padL + h * bw + bw * 0.12}" y="${padT + plotH - hh}" width="${bw * 0.76}" height="${hh}" rx="2"><title>${label}: ${duration(hours[h])}</title></rect>`;
      })
      .join("");
    const labels = [0, 3, 6, 9, 12, 15, 18, 21]
      .map((h) => `<text x="${padL + h * bw + bw / 2}" y="${H - 6}" text-anchor="middle">${new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" })}</text>`)
      .join("");
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Music by hour of the day">${grid}${bars}${labels}</svg>`;
  }

  // Played music --------------------------------------------------------------------

  _renderLibrary() {
    const lib = this._library;
    const stale = !lib || lib.entry_id !== this._selected || lib.view !== this._libView || lib.sort !== this._libSort || lib.query !== this._libQuery;
    if (stale && !this._loadingLibrary) {
      this._loadingLibrary = true;
      this._loadLibrary().finally(() => (this._loadingLibrary = false));
    }
    const toolbar = `<div class="toolbar">${this._picker()}
      <div class="search">${icon("search")}<input type="search" id="lib-search" placeholder="Search songs, artists, albums" value="${esc(this._libQuery)}" aria-label="Search played music"></div>
      <div class="seg" role="group" aria-label="Show">
        <button data-libview="songs" aria-pressed="${this._libView === "songs"}">Songs</button>
        <button data-libview="artists" aria-pressed="${this._libView === "artists"}">Artists</button>
      </div>
      ${this._libView === "songs" ? `<div class="seg" role="group" aria-label="Sort">
        <button data-libsort="last" aria-pressed="${this._libSort === "last"}">Recent</button>
        <button data-libsort="plays" aria-pressed="${this._libSort === "plays"}">Most played</button>
        <button data-libsort="seconds" aria-pressed="${this._libSort === "seconds"}">Most time</button>
      </div>` : ""}
    </div>`;
    if (!lib || lib.entry_id !== this._selected) return `${toolbar}<p class="empty">Loading played music…</p>`;
    const id = this._selected;
    const note = this._notes.block ? `<div style="margin-bottom:12px">${this._note("block")}</div>` : "";
    if (!lib.items.length) {
      return `${toolbar}${note}<div class="empty"><h2>${lib.query ? "Nothing matches" : "Nothing played yet"}</h2><p>${lib.query ? "Try another search." : "Songs show up here as they play, so you can block them or play an artist on a schedule."}</p></div>`;
    }
    const unblock = (b) => `<button class="btn small" data-unblock="${esc(b.kind)}" data-value="${esc(b.rule)}" data-id="${id}">Unblock</button>`;
    let table;
    if (lib.view === "artists") {
      table = `<table class="lib"><thead><tr><th>Artist</th><th class="num">Plays</th><th class="num hide-sm">Time</th><th class="hide-sm">Last played</th><th></th></tr></thead><tbody>${lib.items
        .map((a) => `<tr class="${a.blocked ? "is-blocked" : ""}">
          <td><span class="song">${esc(a.artist)}${a.blocked ? `<span class="badge">Blocked</span>` : ""}<small>${a.songs} song${a.songs === 1 ? "" : "s"}${a.source ? ` · ${esc(a.source)}` : ""}</small></span></td>
          <td class="num">${a.plays}</td><td class="num hide-sm">${duration(a.seconds)}</td><td class="hide-sm muted">${esc(agoLabel(a.last))}</td>
          <td><div class="acts">
            ${a.blocked ? unblock(a.blocked) : `<button class="btn small" data-block="artist" data-value="${esc(a.artist)}" data-id="${id}">${icon("block")} Block</button>`}
            <button class="btn small" data-schedule-artist="${esc(a.artist)}" data-id="${id}" title="Play ${esc(a.artist)} on a schedule">${icon("calendar")} Schedule</button>
          </div></td></tr>`)
        .join("")}</tbody></table>`;
    } else {
      table = `<table class="lib"><thead><tr><th>Song</th><th class="hide-sm">Album</th><th class="num">Plays</th><th class="num hide-sm">Time</th><th class="hide-sm">Last played</th><th></th></tr></thead><tbody>${lib.items
        .map((t) => `<tr class="${t.blocked ? "is-blocked" : ""}">
          <td><span class="song">${esc(t.title)}${t.blocked ? `<span class="badge">Blocked</span>` : ""}<small>${esc(t.artist || "Unknown artist")}${t.source ? ` · ${esc(t.source)}` : ""}</small></span></td>
          <td class="hide-sm muted">${esc(t.album || "")}</td>
          <td class="num">${t.plays}</td><td class="num hide-sm">${duration(t.seconds)}</td><td class="hide-sm muted">${esc(agoLabel(t.last))}</td>
          <td><div class="acts">
            ${t.blocked
              ? unblock(t.blocked)
              : `<button class="btn small" data-block="track" data-value="${esc(trackEntry(t.title, t.artist))}" data-id="${id}">${icon("block")} Song</button>
                 ${t.artist ? `<button class="btn small" data-block="artist" data-value="${esc(t.artist)}" data-id="${id}">${icon("block")} Artist</button>` : ""}`}
          </div></td></tr>`)
        .join("")}</tbody></table>`;
    }
    return `${toolbar}${note}<section class="card"><div class="card-body" style="padding:6px 8px;overflow-x:auto">${table}</div></section>
      <p class="muted">Showing ${lib.items.length} of ${lib.total} songs this speaker has played. Media Mgmt keeps the most recent 3000.</p>`;
  }

  // Schedules -------------------------------------------------------------------------

  _renderSchedules() {
    const p = this._profile;
    if (!p) return "";
    if (this._schedEdit && this._schedEdit.entry_id === p.entry_id) return `<div class="toolbar">${this._picker()}</div>${this._renderSchedEditor(p)}`;
    const list = (p.schedules || [])
      .slice()
      .sort((a, b) => (a.start || a.stop).localeCompare(b.start || b.stop))
      .map((s) => this._schedCard(p, s))
      .join("");
    const intro = `<section class="card"><div class="card-body">
      <div class="card-head"><h2>Schedules for ${esc(p.name)}</h2><div class="row">
        <button class="btn" data-new-limit="${p.entry_id}">${icon("volume")} Add volume limit</button>
        <button class="btn primary" data-new-schedule="${p.entry_id}">${icon("plus")} Add schedule</button></div></div>
      <p class="muted" style="margin:0">Start music at a set time, like an artist your kids fall asleep to, and fade it out and stop it at a set time, on the nights you pick. A schedule with only a stop time is a nightly sleep timer. While a schedule plays, the daily limit and quiet windows don't stop it.</p>
      <p class="muted" style="margin:0">A volume limit plays nothing: between its times, like early mornings, the speaker can't be turned up past the limit.</p>
      ${this._note("sched")}
    </div></section>`;
    return `<div class="toolbar">${this._picker()}</div><div class="stack">${intro}${list ? `<section class="card"><div class="card-body">${list}</div></section>` : `<div class="empty"><p>No schedules yet.</p></div>`}</div>`;
  }

  _schedWhat(s) {
    const v = esc(s.play_value);
    return {
      artist: `Plays music by <strong>${v}</strong>`,
      album: `Plays the album <strong>${v}</strong>`,
      track: `Plays <strong>${v}</strong>`,
      playlist: `Plays the playlist <strong>${v}</strong>`,
      source: `Plays <strong>${v}</strong>`,
      content: `Plays <strong>${v}</strong>`,
      resume: "Resumes whatever played last",
      none: `Limits the volume to <strong>${s.volume_limit}%</strong>. Nothing is played or stopped`,
    }[s.play_kind];
  }

  _schedCard(p, s) {
    const when = s.start ? `${esc(hhmmLabel(s.start))}${s.stop ? `<small>to ${esc(hhmmLabel(s.stop))}</small>` : ""}` : `${esc(hhmmLabel(s.stop))}<small>stop only</small>`;
    const bits = [];
    const limitOnly = s.play_kind === "none";
    if (limitOnly) bits.push(this._schedWhat(s));
    else if (s.start) {
      bits.push(this._schedWhat(s));
      if (s.volume != null) bits.push(`at ${s.volume}% volume`);
      if (s.volume_limit != null) bits.push(`never louder than ${s.volume_limit}%`);
      if (s.shuffle) bits.push("shuffled");
    }
    const stop = s.stop && !limitOnly ? `${s.fade_minutes ? `Fades out over ${s.fade_minutes} min, then ` : ""}${{ pause: "pauses", stop: "stops", turn_off: "turns the speaker off" }[s.stop_action]}${s.start ? "" : " whatever's playing"} at ${esc(hhmmLabel(s.stop))}.` : "";
    const id = p.entry_id;
    return `<div class="sched${s.enabled ? "" : " disabled"}" style="padding:12px 0;border-top:1px solid var(--divider-color)">
      <div class="when">${when}</div>
      <div>
        <h3>${esc(s.name)} ${s.active ? `<span class="chip tone-info">Playing now</span>` : ""}${!s.enabled ? `<span class="chip tone-muted">Off</span>` : ""}</h3>
        <div class="what">${bits.join(", ")}${bits.length ? "." : ""} ${stop}</div>
        <div class="muted">${esc(daysLabel(s.days))}${s.enabled && s.next_run ? ` · next ${esc(whenLabel(s.next_run))}` : ""}${s.start && !s.lift_limits && s.play_kind !== "none" ? " · limits still apply" : ""}</div>
      </div>
      <div class="acts">
        <label class="switch" title="${s.enabled ? "Turn off" : "Turn on"}"><input type="checkbox" data-sched-enable="${esc(s.id)}" data-id="${id}" ${s.enabled ? "checked" : ""} aria-label="${esc(s.name)} on"><span></span></label>
        ${s.start && !limitOnly ? `<button class="btn small" data-run="${esc(s.id)}" data-id="${id}">${icon("play")} Play now</button>` : ""}
        <button class="btn small" data-edit-schedule="${esc(s.id)}" data-id="${id}">${icon("edit")} Edit</button>
        <button class="btn small danger" data-delete-schedule="${esc(s.id)}" data-id="${id}" aria-label="Delete ${esc(s.name)}">${icon("delete")}</button>
      </div>
    </div>`;
  }

  _newSchedule(entryId, extra = {}) {
    return {
      entry_id: entryId,
      id: null,
      name: "Bedtime music",
      enabled: true,
      days: [0, 1, 2, 3, 4, 5, 6],
      start: "19:30",
      stop: "20:30",
      hasStart: true,
      hasStop: true,
      play_kind: "artist",
      play_value: "",
      content_type: "",
      shuffle: true,
      repeat: "all",
      volume: 20,
      setVolume: true,
      limitVolume: true,
      volume_limit: 30,
      fade_minutes: 10,
      stop_action: "pause",
      lift_limits: true,
      ...extra,
    };
  }

  _editSchedule(p, s) {
    this._schedEdit = {
      ...s,
      entry_id: p.entry_id,
      hasStart: !!s.start,
      hasStop: !!s.stop,
      start: s.start || "19:30",
      stop: s.stop || "20:30",
      setVolume: s.volume != null,
      volume: s.volume ?? 20,
      limitVolume: s.volume_limit != null,
      volume_limit: s.volume_limit ?? 30,
      content_type: s.content_type || "",
    };
  }

  async _ensureArtists() {
    if (this._artistsFor === this._selected) return;
    this._artistsFor = this._selected;
    try {
      const res = await this._ws({ type: "media_mgmt/history", entry_id: this._selected, view: "artists", limit: 300 });
      this._artists = res.items;
      const songs = await this._ws({ type: "media_mgmt/history", entry_id: this._selected, view: "songs", sort: "plays", limit: 300 });
      this._songs = songs.items;
      this._render();
    } catch (err) {
      this._artists = [];
    }
  }

  _renderSchedEditor(p) {
    const d = this._schedEdit;
    const limitOnly = d.play_kind === "none";
    this._ensureArtists();
    if (!this._settings || this._settings.for !== p.entry_id) {
      if (!this._loadingSettings) {
        this._loadingSettings = true;
        this._ws({ type: "media_mgmt/settings/get", entry_id: p.entry_id })
          .then((res) => (this._settings = { ...res, for: p.entry_id }))
          .catch(() => {})
          .finally(() => {
            this._loadingSettings = false;
            this._render();
          });
      }
    }
    const caps = p.capabilities || {};
    const sources = this._settings?.for === p.entry_id ? this._settings.sources : [];
    const options = {
      artist: (this._artists || []).slice().sort((a, b) => b.plays - a.plays || b.seconds - a.seconds).map((a) => a.artist),
      album: [...new Set((this._songs || []).map((s) => s.album).filter(Boolean))],
      track: (this._songs || []).map((s) => s.title),
      playlist: [...new Set((this._songs || []).map((s) => s.playlist).filter(Boolean))],
      source: sources,
      content: [...new Set((this._songs || []).map((s) => s.content_id).filter(Boolean))],
    }[d.play_kind] || [];
    const help = {
      artist: caps.music_assistant
        ? "Music Assistant finds the artist's music, so any artist works."
        : "Pick an artist that's played on this speaker before. For a whole artist's music on any speaker, add the speaker through Music Assistant, or use a playlist or favourite.",
      album: caps.music_assistant ? "Music Assistant finds the album." : "Pick an album that's played on this speaker before.",
      track: caps.music_assistant ? "Music Assistant finds the song." : "Pick a song that's played on this speaker before. Turn on repeat to keep it going.",
      playlist: caps.music_assistant ? "Music Assistant finds the playlist by name." : "A playlist that's played before, or paste its link or URI (for example spotify:playlist:…).",
      source: sources.length ? "Favourites, stations and inputs this speaker lists, such as Sonos favourites." : "This speaker doesn't list any sources or favourites.",
      content: "A media content ID the speaker's integration accepts, such as a Spotify URI or a stream URL.",
      resume: "Presses play on whatever the speaker played last.",
    }[d.play_kind];
    const showValue = d.play_kind !== "resume";
    const datalist = options.length ? `<datalist id="play-options">${options.map((o) => `<option value="${esc(o)}"></option>`).join("")}</datalist>` : "";
    return `<section class="card"><div class="card-body">
      <div class="card-head"><h2>${d.id ? (limitOnly ? "Edit volume limit" : "Edit schedule") : limitOnly ? "New volume limit" : "New schedule"}</h2></div>
      <form id="schedule" novalidate>
        <div class="form-grid">
          <div class="field"><label for="s-name">Name</label><input type="text" id="s-name" data-s="name" value="${esc(d.name)}" maxlength="60"></div>
          <label class="toggle field" style="align-self:end"><span>Turned on</span><span class="switch"><input type="checkbox" data-s="enabled" ${d.enabled ? "checked" : ""}><span></span></span></label>
        </div>
        <div class="field">
          <span class="label">What it does</span>
          <div class="seg wide" role="group" aria-label="What it does">
            <button type="button" data-sched-mode="music" aria-pressed="${!limitOnly}">Play music</button>
            <button type="button" data-sched-mode="limit" aria-pressed="${limitOnly}">Only limit the volume</button>
          </div>
        </div>
        <div class="field">
          <span class="label">Days</span>
          <div class="days">${DAYS.map((name, i) => `<label><input type="checkbox" data-sday="${i}" ${d.days.includes(i) ? "checked" : ""}><span>${name}</span></label>`).join("")}</div>
          <div class="row">${DAY_PRESETS.map((pr, i) => `<button type="button" class="chip-btn" data-day-preset="${i}">${pr.label}</button>`).join("")}</div>
          <small>A schedule that runs past midnight belongs to the day it starts. School nights are Sunday to Thursday.</small>
        </div>
        <div class="form-grid">
          <div class="field">
            ${limitOnly ? `<label for="s-start">Limit starts at</label>` : `<label class="radio"><input type="checkbox" class="check" data-s="hasStart" ${d.hasStart ? "checked" : ""}> Start music at</label>`}
            <input type="time" id="s-start" data-s="start" value="${esc(d.start)}" ${d.hasStart ? "" : "disabled"} aria-label="Start time">
          </div>
          <div class="field">
            ${limitOnly ? `<label for="s-stop">Limit ends at</label>` : `<label class="radio"><input type="checkbox" class="check" data-s="hasStop" ${d.hasStop ? "checked" : ""}> Stop music at</label>`}
            <input type="time" id="s-stop" data-s="stop" value="${esc(d.stop)}" ${d.hasStop ? "" : "disabled"} aria-label="Stop time">
          </div>
        </div>
        ${limitOnly ? `
        <div class="field"><label for="s-limit">Limit the volume to</label>
          <span class="inline"><input type="number" id="s-limit" min="5" max="100" step="5" data-s="volume_limit" value="${d.volume_limit}"> %</span>
          <small>Between these times, turning the speaker up past this turns it straight back down. Nothing is played or stopped, and the daily limit and quiet windows still apply.${p.max_volume < 100 ? ` The speaker's ${p.max_volume}% cap still applies if it's lower.` : ""}</small>
        </div>` : ""}
        ${d.hasStart && !limitOnly ? `
        <div class="form-grid">
          <div class="field"><label for="s-kind">Play</label>
            <select id="s-kind" data-s="play_kind">${PLAY_KINDS.map((k) => `<option value="${k.id}" ${d.play_kind === k.id ? "selected" : ""}>${k.label}</option>`).join("")}</select></div>
          ${showValue ? `<div class="field"><label for="s-value">${{ artist: "Artist", album: "Album", track: "Song", playlist: "Playlist", source: "Favourite or source", content: "Media ID" }[d.play_kind]}</label>
            ${d.play_kind === "source" && sources.length
              ? `<select id="s-value" data-s="play_value"><option value="">Pick one</option>${sources.map((s) => `<option ${s === d.play_value ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>`
              : `<input type="text" id="s-value" data-s="play_value" value="${esc(d.play_value)}" list="play-options" autocomplete="off">${datalist}`}
            ${["artist", "album", "track"].includes(d.play_kind) && options.length
              ? `<div class="presets" role="group" aria-label="Played on this speaker before"><span class="muted" style="font-size:13px;width:100%">Played on this speaker before, most played first</span>${options
                  .slice(0, 12)
                  .map((o) => `<button type="button" class="chip-btn" data-play-value="${esc(o)}" aria-pressed="${o === d.play_value}">${esc(o)}</button>`)
                  .join("")}</div>`
              : ""}
          </div>` : ""}
          ${d.play_kind === "content" ? `<div class="field"><label for="s-ctype">Content type</label><input type="text" id="s-ctype" data-s="content_type" value="${esc(d.content_type)}" placeholder="music"></div>` : ""}
        </div>
        <small class="muted" style="margin-top:-12px">${esc(help)}</small>
        <div class="form-grid">
          <div class="field">
            <label class="radio"><input type="checkbox" class="check" data-s="setVolume" ${d.setVolume ? "checked" : ""}> Set the volume to</label>
            <span class="inline"><input type="number" min="0" max="100" step="5" data-s="volume" value="${d.volume}" ${d.setVolume ? "" : "disabled"} aria-label="Volume"> %</span>
            ${p.max_volume < 100 ? `<small>The volume cap of ${p.max_volume}% still applies.</small>` : ""}
          </div>
          ${d.hasStop ? `<div class="field">
            <label class="radio"><input type="checkbox" class="check" data-s="limitVolume" ${d.limitVolume ? "checked" : ""}> Limit the volume to</label>
            <span class="inline"><input type="number" min="5" max="100" step="5" data-s="volume_limit" value="${d.volume_limit}" ${d.limitVolume ? "" : "disabled"} aria-label="Volume limit"> %</span>
            <small>While this schedule plays, turning the speaker up past this turns it straight back down. The usual cap comes back when it stops.</small>
          </div>` : ""}
          <div class="field"><span class="label">Order</span>
            <label class="radio"><input type="checkbox" class="check" data-s="shuffle" ${d.shuffle ? "checked" : ""} ${caps.shuffle === false ? "" : ""}> Shuffle</label>
            <label class="radio">Repeat <select data-s="repeat">${[["off", "Off"], ["all", "All"], ["one", "One song"]].map(([v, l]) => `<option value="${v}" ${d.repeat === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          </div>
        </div>` : ""}
        ${d.hasStop && !limitOnly ? `
        <div class="form-grid">
          <div class="field"><label for="s-fade">Fade out before stopping</label>
            <span class="inline"><input type="number" id="s-fade" min="0" max="60" data-s="fade_minutes" value="${d.fade_minutes}"> minutes</span>
            <small>The volume goes down slowly, then comes back up after the music stops, ready for next time.</small></div>
          <div class="field"><span class="label">At the stop time</span>
            ${STOP_ACTIONS.map((a) => `<label class="radio"><input type="radio" name="stop_action" data-s="stop_action" value="${a.id}" ${d.stop_action === a.id ? "checked" : ""}> ${a.label}</label>`).join("")}</div>
        </div>` : ""}
        ${d.hasStart && d.hasStop && !limitOnly ? `<label class="toggle"><span>Play through limits<small>The daily limit and quiet windows don't stop this schedule's music, and its time doesn't count toward the limit. Stop music now still does.</small></span>
          <span class="switch"><input type="checkbox" data-s="lift_limits" ${d.lift_limits ? "checked" : ""}><span></span></span></label>` : ""}
        <div class="form-actions">
          <button type="submit" class="btn primary" ${this._busy ? "disabled" : ""}>${this._busy ? "Saving…" : "Save schedule"}</button>
          <button type="button" class="btn" data-cancel-schedule>Cancel</button>
        </div>
      </form>
    </div></section>`;
  }

  // Copy what's in the schedule form into the draft.
  _syncSchedForm() {
    this.shadowRoot.querySelectorAll("#schedule [data-s]").forEach((el) => {
      if (el.type === "radio") {
        if (el.checked) this._schedEdit[el.dataset.s] = el.value;
      } else this._schedEdit[el.dataset.s] = el.type === "checkbox" ? el.checked : el.value;
    });
  }

  async _saveSchedule() {
    const d = this._schedEdit;
    if (!d.hasStart && !d.hasStop) return this._showError("Give the schedule a start time, a stop time, or both.");
    if (!d.days.length) return this._showError("Pick at least one day.");
    const limitOnly = d.play_kind === "none";
    if (limitOnly && (!d.start || !d.stop)) return this._showError("Give the volume limit a start and an end time.");
    if (limitOnly && d.start === d.stop) return this._showError("The volume limit starts and ends at the same time.");
    if (d.hasStart && !limitOnly && d.play_kind !== "resume" && !String(d.play_value).trim()) return this._showError("Say what to play.");
    if (d.hasStart && d.hasStop && d.limitVolume) {
      const limit = Number(d.volume_limit);
      if (!Number.isInteger(limit) || limit < 5 || limit > 100) return this._showError("Limit the volume to a whole number from 5 to 100%.");
      if (!limitOnly && d.setVolume && Number(d.volume) > limit) return this._showError(`The starting volume (${d.volume}%) is above the limit (${limit}%). Lower it, or raise the limit.`);
    }
    const schedule = {
      id: d.id || null,
      name: d.name.trim() || "Schedule",
      enabled: d.enabled,
      days: d.days,
      start: d.hasStart ? d.start : null,
      stop: d.hasStop ? d.stop : null,
      play_kind: d.play_kind,
      play_value: String(d.play_value || "").trim(),
      content_type: d.content_type || null,
      shuffle: d.shuffle,
      repeat: d.repeat,
      volume: d.hasStart && d.setVolume && !limitOnly ? Number(d.volume) : null,
      volume_limit: d.hasStart && d.hasStop && (d.limitVolume || limitOnly) ? Number(d.volume_limit) : null,
      fade_minutes: d.hasStop ? Number(d.fade_minutes) || 0 : 0,
      stop_action: d.stop_action,
      lift_limits: d.lift_limits,
    };
    this._busy = true;
    this._error = null;
    this._render();
    try {
      await this._ws({ type: "media_mgmt/schedule/save", entry_id: d.entry_id, schedule });
      this._schedEdit = null;
      this._notes.sched = `Saved ${schedule.name}`;
      this._busy = false;
      await this._loadProfiles();
    } catch (err) {
      this._busy = false;
      this._showError(err);
    }
  }

  async _scheduleRequest(entryId, msg, note) {
    try {
      const res = await this._ws({ entry_id: entryId, ...msg });
      if (msg.type === "media_mgmt/schedule/run") {
        this._notes.sched = res.ok ? "Playing" : `Couldn't play: ${res.detail || "the speaker didn't take it"}`;
        if (!res.ok) this._error = this._notes.sched;
      } else if (note) this._notes.sched = note;
      if (res.ok !== false) this._error = null;
    } catch (err) {
      this._error = this._errorText(err);
    }
    await this._loadProfiles();
  }

  // Rules ------------------------------------------------------------------------------

  _renderRules() {
    const d = this._draft;
    if (!d || this._settings?.for !== this._selected) {
      if (!this._loadingSettings) {
        this._loadingSettings = true;
        this._loadSettings().finally(() => (this._loadingSettings = false));
      }
      return `<div class="toolbar">${this._picker()}</div><p class="empty">Loading rules…</p>`;
    }
    const windows = d.windows
      .map((w, i) => `<div class="window">
          <input type="time" aria-label="Starts" data-win="${i}" data-key="start" value="${esc(w.start)}">
          <input type="time" aria-label="Ends" data-win="${i}" data-key="end" value="${esc(w.end)}">
          <input type="text" aria-label="Name" placeholder="Name, e.g. Bedtime" data-win="${i}" data-key="label" value="${esc(w.label)}">
          <button type="button" class="btn" data-remove-window="${i}" aria-label="Remove this quiet window">${icon("delete")}</button>
        </div>`)
      .join("");
    const listening = `<section class="card"><div class="card-body">
      <div class="card-head"><h2>Listening time</h2></div>
      <form id="listening" novalidate>
        <div class="form-grid">
          <div class="field"><label for="daily_budget">Daily listening time</label>
            <span class="inline"><input id="daily_budget" type="number" min="0" max="1440" step="5" value="${d.daily_budget}"> minutes</span>
            <small>0 means no daily limit. Only time spent playing counts.</small></div>
          <div class="field"><label for="warn_minutes">Warn before time runs out</label>
            <span class="inline"><input id="warn_minutes" type="number" min="0" max="60" value="${d.warn_minutes}"> minutes</span>
            <small>Said on the speaker if spoken warnings are set up, and fires media_mgmt_warning.</small></div>
          <div class="field"><label for="adult_mode_duration">Adult mode lasts</label>
            <span class="inline"><input id="adult_mode_duration" type="number" min="5" max="720" step="5" value="${d.adult_mode_duration}"> minutes</span></div>
        </div>
        <div class="field"><span class="label">Quiet windows</span>
          <small>Times music stays off, like bedtime or school hours. A window can run past midnight. Schedules can still play during them.</small>
          <div class="windows">${windows || `<p class="muted">No quiet windows.</p>`}</div>
          <span><button type="button" class="btn" data-add-window>${icon("plus")} Add quiet window</button></span></div>
        <div class="field"><span class="label">When music isn't allowed</span>
          <div class="row">${LIMIT_ACTIONS.map((a) => `<label class="radio"><input type="radio" name="limit_action" value="${a.id}" ${d.limit_action === a.id ? "checked" : ""}> ${a.label}</label>`).join("")}</div></div>
        <div class="form-actions"><button type="submit" class="btn primary" ${this._busy ? "disabled" : ""}>Save listening time</button>${this._note("listening")}</div>
      </form></div></section>`;

    const rules = Object.keys(KIND_LABELS)
      .map((kind) => {
        const values = d.filter[kind] || [];
        return `<div class="rule-group"><div class="label"><span>${KIND_PLURAL[kind]}</span><span class="muted">${values.length || ""}</span></div>
          ${values.length ? `<div class="rule-chips">${values.map((v) => `<span class="rule-chip">${esc(v)}<button type="button" data-unblock="${kind}" data-value="${esc(v)}" data-id="${this._selected}" aria-label="Unblock ${esc(v)}">${icon("delete")}</button></span>`).join("")}</div>` : `<span class="muted">None</span>`}
        </div>`;
      })
      .join("");
    const filter = `<section class="card"><div class="card-body">
      <div class="card-head"><h2>Blocked music</h2><button class="btn small" data-goto="library">${icon("search")} Block from played music</button></div>
      <p class="muted" style="margin:0">Blocked music is ${{ skip: "skipped", pause: "paused", stop: "stopped" }[d.filter_action]} as soon as it starts. Blocking an artist also blocks songs they're featured on. Song names match their remastered and live versions too.</p>
      <form id="add-rule" class="add-rule" novalidate>
        <select id="rule-kind" aria-label="What to block">${Object.entries(KIND_LABELS).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
        <input type="text" id="rule-value" placeholder="Name, or Song — Artist" aria-label="What to block" autocomplete="off">
        <button type="submit" class="btn primary">${icon("block")} Block</button>
      </form>
      ${this._note("block")}
      <div class="rules">${rules}</div>
      <form id="filter-action" novalidate>
        <div class="field"><span class="label">When blocked music plays</span>
          <div class="row">${FILTER_ACTIONS.map((a) => `<label class="radio"><input type="radio" name="filter_action" value="${a.id}" ${d.filter_action === a.id ? "checked" : ""}> ${a.label}</label>`).join("")}</div>
          ${d.capabilities && !d.capabilities.next ? `<small>This speaker can't skip songs, so blocked music is paused instead.</small>` : ""}</div>
        <div class="form-actions"><button type="submit" class="btn">Save</button>${this._note("filter_action")}</div>
      </form>
    </div></section>`;

    const volume = `<section class="card"><div class="card-body">
      <div class="card-head"><h2>Volume</h2></div>
      <form id="volume" novalidate>
        <div class="field"><label for="max_volume">Maximum volume</label>
          <div class="vol" style="max-width:420px"><div class="vol-range"><input type="range" id="max_volume" min="5" max="100" step="5" value="${d.max_volume}"></div><output id="max_volume_out">${d.max_volume >= 100 ? "No cap" : `${d.max_volume}%`}</output></div>
          <small>If someone turns the speaker up past this, it's turned straight back down. 100% means no cap.</small></div>
        <div class="form-actions"><button type="submit" class="btn primary">Save volume</button>${this._note("volume")}</div>
      </form></div></section>`;

    const speakers = (d.speakers || []).filter((s) => s.entity_id !== this._profile?.entity_id);
    const warnings = `<section class="card"><div class="card-body">
      <div class="card-head"><h2>Spoken warnings</h2></div>
      <form id="warnings" novalidate>
        <p class="muted" style="margin:0">Say “5 minutes of music left” when time is running low, and “the music is stopping now” just before it stops.</p>
        <div class="field"><label for="announce_tts">Voice</label>
          <select id="announce_tts"><option value="">None, don't say warnings</option>${(d.tts_entities || []).map((t) => `<option ${t === d.announce_tts ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
          ${(d.tts_entities || []).length ? "" : `<small>Add a text-to-speech integration, such as Piper or Google Translate, to say warnings.</small>`}</div>
        <label class="radio"><input type="checkbox" class="check" id="announce_on_player" ${d.announce_on_player ? "checked" : ""} ${d.capabilities?.announce ? "" : "disabled"}> Say it on this speaker, over the music${d.capabilities?.announce ? "" : " (this speaker can't make announcements)"}</label>
        <div class="field"><span class="label">Also say it on</span>
          <div class="speakers-pick">${speakers.map((s) => `<label class="radio"><input type="checkbox" class="check" data-announce-player="${esc(s.entity_id)}" ${(d.announce_players || []).includes(s.entity_id) ? "checked" : ""}> ${esc(s.name)}${speakers.filter((x) => x.name === s.name).length > 1 ? ` <small class="muted">${esc(s.entity_id)}</small>` : ""}</label>`).join("") || `<span class="muted">No other speakers.</span>`}</div></div>
        <div class="form-actions"><button type="submit" class="btn primary">Save warnings</button>${this._note("warnings")}</div>
      </form></div></section>`;

    return `<div class="toolbar">${this._picker()}</div><div class="stack">${listening}${filter}${volume}${warnings}</div>`;
  }

  _syncRules() {
    const root = this.shadowRoot;
    const d = this._draft;
    for (const key of ["daily_budget", "warn_minutes", "adult_mode_duration", "max_volume"]) {
      const el = root.getElementById(key);
      if (el) d[key] = el.value;
    }
    root.querySelectorAll("[data-win]").forEach((el) => (d.windows[Number(el.dataset.win)][el.dataset.key] = el.value));
    const limit = root.querySelector('input[name="limit_action"]:checked');
    if (limit) d.limit_action = limit.value;
    const fa = root.querySelector('input[name="filter_action"]:checked');
    if (fa) d.filter_action = fa.value;
    const tts = root.getElementById("announce_tts");
    if (tts) d.announce_tts = tts.value || null;
    const onp = root.getElementById("announce_on_player");
    if (onp) d.announce_on_player = onp.checked;
    const players = root.querySelectorAll("[data-announce-player]");
    if (players.length) d.announce_players = [...players].filter((el) => el.checked).map((el) => el.dataset.announcePlayer);
  }

  async _saveSettings(note, payload) {
    this._busy = true;
    this._error = null;
    this._render();
    try {
      await this._ws({ type: "media_mgmt/settings/set", entry_id: this._selected, ...payload });
      this._notes[note] = "Saved";
      this._busy = false;
      await this._loadSettings();
      await this._loadProfiles({ quiet: true });
    } catch (err) {
      this._busy = false;
      this._showError(err);
    }
  }

  // Access -----------------------------------------------------------------------------

  _renderAccess() {
    const d = this._accessDraft;
    if (!d) {
      if (!this._loadingAccess) {
        this._loadingAccess = true;
        this._ws({ type: "media_mgmt/access/get" })
          .then((res) => (this._accessDraft = { people: res.people, ids: new Set(res.user_ids) }))
          .catch((err) => (this._error = this._errorText(err)))
          .finally(() => {
            this._loadingAccess = false;
            this._render();
          });
      }
      return `<p class="empty">Loading people…</p>`;
    }
    const rows = d.people
      .map((u, i) => {
        const checked = u.is_admin || d.ids.has(u.id);
        return `<div class="person">
          <input type="checkbox" class="check" id="person-${i}" data-person="${esc(u.id)}" ${checked ? "checked" : ""} ${u.is_admin ? "disabled" : ""}>
          <label for="person-${i}">${esc(u.name)}</label>
          <span class="tag">${u.is_owner ? "Owner" : u.is_admin ? "Admin" : ""}</span>
        </div>`;
      })
      .join("");
    const nonAdmins = [...d.ids].some((uid) => d.people.some((u) => u.id === uid && !u.is_admin));
    return `<section class="card"><div class="card-body">
      <form id="access" novalidate>
        <div class="field"><label>Who can use Media Mgmt</label>
          <small>Admins always can. Check the other people who can use this app and change Media Mgmt's switches, mode, buttons and actions, such as a parent who isn't an admin. Everyone else, kids included, is turned away. Automations aren't affected.</small></div>
        <div class="people">${rows}</div>
        <small class="muted">${nonAdmins ? "Home Assistant can't show a sidebar entry to only some people, so everyone will see Media Mgmt in the sidebar. People who aren't checked get a page saying they don't have access." : "Only admins see Media Mgmt in the sidebar."}</small>
        <div class="form-actions"><button class="btn primary" type="submit" ${this._busy ? "disabled" : ""}>Save</button>${this._note("access")}</div>
      </form></div></section>`;
  }

  async _saveAccess() {
    this._busy = true;
    this._render();
    try {
      const res = await this._ws({ type: "media_mgmt/access/set", user_ids: [...this._accessDraft.ids] });
      this._accessDraft = { people: res.people, ids: new Set(res.user_ids) };
      this._notes.access = "Access saved";
      this._error = null;
    } catch (err) {
      this._error = this._errorText(err);
    }
    this._busy = false;
    this._render();
  }

  // Speakers ---------------------------------------------------------------------------

  _renderSpeakers() {
    if (!this._candidates) {
      if (!this._loadingCandidates) {
        this._loadingCandidates = true;
        this._ws({ type: "media_mgmt/speakers/candidates" })
          .then((res) => (this._candidates = res.players))
          .catch((err) => {
            this._candidates = [];
            this._error = this._errorText(err);
          })
          .finally(() => {
            this._loadingCandidates = false;
            this._render();
          });
      }
      return `<p class="empty">Loading speakers…</p>`;
    }
    const managed = (this._profiles || [])
      .map((p) => `<div class="person">
          ${icon("speaker")}
          <span>${esc(p.name)}<small class="muted" style="display:block">${esc(p.entity_id)}</small></span>
          <button class="btn small danger" data-remove-speaker="${p.entry_id}" data-name="${esc(p.name)}">${icon("delete")} Remove</button>
        </div>`)
      .join("");
    // Two speakers can share a name (a Sonos and a Cast group, say): show the entity ID then.
    const names = [...this._candidates.map((c) => c.name), ...(this._profiles || []).map((p) => p.name)];
    const dup = (name) => names.filter((n) => n === name).length > 1;
    const options = this._candidates
      .map((c) => {
        const where = dup(c.name) ? c.entity_id : c.platform ? c.platform.replace(/_/g, " ") : "";
        return `<option value="${esc(c.entity_id)}">${esc(c.name)}${where ? ` (${esc(where)})` : ""}</option>`;
      })
      .join("");
    const add = this._candidates.length
      ? `<form id="add-speaker" class="add-rule" novalidate>
          <select id="new-speaker" aria-label="Speaker to add">${options}</select>
          <button type="submit" class="btn primary" ${this._busy ? "disabled" : ""}>${icon("plus")} Add</button>
        </form>
        <small class="muted">It starts with no limits and nothing blocked, so nothing changes until you set rules. Speakers added through Music Assistant can play any artist on a schedule.</small>`
      : `<p class="muted">Every media player in Home Assistant is already managed.</p>`;
    return `<div class="stack">
      <section class="card"><div class="card-body">
        <div class="card-head"><h2>Add a speaker</h2></div>
        <p class="muted" style="margin:0">Any media player Home Assistant runs: Sonos, HomePod, Google and Nest speakers, Music Assistant, Spotify, Alexa and others.</p>
        ${add}
        ${this._note("speakers")}
      </div></section>
      <section class="card"><div class="card-body">
        <div class="card-head"><h2>Managed speakers</h2></div>
        ${managed ? `<div class="people">${managed}</div>` : `<p class="muted">None yet.</p>`}
        <small class="muted">Removing a speaker deletes its history, rules and schedules. The speaker itself isn't touched.</small>
      </div></section>
    </div>`;
  }

  async _speakerRequest(msg, note) {
    this._busy = true;
    this._error = null;
    this._render();
    try {
      const res = await this._ws(msg);
      this._notes.speakers = note(res);
      if (res.entry_id) this._selected = res.entry_id;
    } catch (err) {
      this._error = this._errorText(err);
    }
    this._busy = false;
    this._candidates = null;
    await this._loadProfiles();
  }

  // ---- events --------------------------------------------------------------------------

  _onClick(ev) {
    const el = ev.target.closest("button");
    if (!el) return;
    const ds = el.dataset;
    if (ds.tab) {
      this._tab = ds.tab;
      this._error = null;
      this._notes = {};
      if (ds.tab === "access") this._accessDraft = null;
      if (ds.tab === "speakers") this._candidates = null;
      if (ds.tab === "rules") {
        this._draft = null;
        this._settings = null;
      }
      if (ds.tab !== "schedules") this._schedEdit = null;
      this._render();
      return;
    }
    if (ds.expand) {
      this._toggleExpanded(ds.expand);
      return;
    }
    if (ds.playValue !== undefined && this._schedEdit) {
      this._schedEdit.play_value = ds.playValue;
      this._render();
      return;
    }
    if (ds.removeSpeaker) {
      if (!window.confirm(`Stop managing ${ds.name}? Its history, rules and schedules are deleted.`)) return;
      this._speakerRequest({ type: "media_mgmt/speakers/remove", entry_id: ds.removeSpeaker }, () => `Removed ${ds.name}`);
      return;
    }
    if (ds.goto) {
      if (ds.id) this._selected = ds.id;
      this._tab = ds.goto;
      this._notes = {};
      this._render();
      return;
    }
    if (ds.pick) {
      if (this._tab === "analytics") {
        this._analyticsScope = ds.pick;
        if (ds.pick !== "all") this._selected = ds.pick;
      } else {
        this._selected = ds.pick;
        this._analyticsScope = null;
      }
      this._activity = null;
      this._activityDate = null;
      this._draft = null;
      this._settings = null;
      this._schedEdit = null;
      this._notes = {};
      this._render();
      return;
    }
    if (ds.act) {
      if (ds.confirm && !window.confirm(ds.confirm)) return;
      const extra = {};
      if (ds.minutes) extra.minutes = Number(ds.minutes);
      if (ds.mode) extra.mode = ds.mode;
      this._action(ds.id, ds.act, extra);
      return;
    }
    if (ds.sleep) {
      const fade = this._notes[`fade-${ds.id}`] ?? true;
      const mins = Number(ds.sleep);
      this._action(ds.id, "set_sleep_timer", { minutes: mins, fade_minutes: fade ? Math.min(10, Math.max(1, Math.round(mins / 3))) : 0 });
      return;
    }
    if (ds.block) {
      this._block(ds.id, ds.block, ds.value, true);
      return;
    }
    if (ds.unblock) {
      if (!window.confirm(`Unblock ${KIND_LABELS[ds.unblock].toLowerCase()} “${ds.value}”?`)) return;
      this._block(ds.id, ds.unblock, ds.value, false);
      return;
    }
    if (ds.media) {
      this._callService("media_player", ds.media, { entity_id: ds.eid });
      return;
    }
    if (ds.moreInfo) {
      this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: ds.moreInfo }, bubbles: true, composed: true }));
      return;
    }
    if (ds.day) {
      const a = this._activity;
      this._activityDate = ds.day === "today" ? a.today : shiftDate(a.date, Number(ds.day));
      this._loadActivity();
      return;
    }
    if (ds.range) {
      this._range = Number(ds.range);
      this._render();
      return;
    }
    if (ds.libview) {
      this._libView = ds.libview;
      this._render();
      return;
    }
    if (ds.libsort) {
      this._libSort = ds.libsort;
      this._render();
      return;
    }
    if (ds.run) {
      this._scheduleRequest(ds.id, { type: "media_mgmt/schedule/run", schedule_id: ds.run });
      return;
    }
    if (ds.newLimit) {
      this._schedEdit = this._newSchedule(ds.newLimit, { name: "Early morning", play_kind: "none", start: "06:00", stop: "08:00", limitVolume: true, volume_limit: 20 });
      this._error = null;
      this._render();
      return;
    }
    if (ds.schedMode && this._schedEdit) {
      this._syncSchedForm();
      const d = this._schedEdit;
      if (ds.schedMode === "limit" && d.play_kind !== "none") {
        d.musicKind = d.play_kind;
        Object.assign(d, { play_kind: "none", hasStart: true, hasStop: true, limitVolume: true });
      } else if (ds.schedMode === "music" && d.play_kind === "none") {
        d.play_kind = d.musicKind || "artist";
      }
      this._render();
      return;
    }
    if (ds.newSchedule) {
      this._schedEdit = this._newSchedule(ds.newSchedule);
      this._error = null;
      this._render();
      return;
    }
    if (ds.scheduleArtist) {
      this._selected = ds.id;
      this._tab = "schedules";
      this._schedEdit = this._newSchedule(ds.id, { name: `${ds.scheduleArtist} at bedtime`, play_kind: "artist", play_value: ds.scheduleArtist });
      this._notes = {};
      this._render();
      return;
    }
    if (ds.editSchedule) {
      const p = this._profiles.find((x) => x.entry_id === ds.id);
      const s = p?.schedules.find((x) => x.id === ds.editSchedule);
      if (s) this._editSchedule(p, s);
      this._render();
      return;
    }
    if (ds.deleteSchedule) {
      const p = this._profiles.find((x) => x.entry_id === ds.id);
      const s = p?.schedules.find((x) => x.id === ds.deleteSchedule);
      if (!window.confirm(`Delete the schedule ${s?.name ?? ""}?`)) return;
      this._scheduleRequest(ds.id, { type: "media_mgmt/schedule/delete", schedule_id: ds.deleteSchedule }, "Deleted");
      return;
    }
    if (el.hasAttribute("data-cancel-schedule")) {
      this._schedEdit = null;
      this._error = null;
      this._render();
      return;
    }
    if (ds.dayPreset !== undefined) {
      this._schedEdit.days = [...DAY_PRESETS[Number(ds.dayPreset)].days];
      this._render();
      return;
    }
    if (el.hasAttribute("data-add-window")) {
      this._syncRules();
      this._draft.windows.push({ start: "20:00", end: "07:00", label: "Bedtime" });
      this._render();
      return;
    }
    if (ds.removeWindow !== undefined) {
      this._syncRules();
      this._draft.windows.splice(Number(ds.removeWindow), 1);
      this._render();
    }
  }

  _onChange(ev) {
    const el = ev.target;
    const ds = el.dataset;
    if (ds.volume) {
      this._callService("media_player", "volume_set", { entity_id: ds.volume, volume_level: Number(el.value) / 100 });
      return;
    }
    if (ds.fade) {
      this._notes[`fade-${ds.fade}`] = el.checked;
      return;
    }
    if (ds.toggle) {
      this._action(ds.id, ds.toggle, { enabled: el.checked });
      return;
    }
    if (ds.schedEnable) {
      const p = this._profiles.find((x) => x.entry_id === ds.id);
      const s = p?.schedules.find((x) => x.id === ds.schedEnable);
      if (s) {
        const { next_run, active, ...plain } = s;
        this._scheduleRequest(ds.id, { type: "media_mgmt/schedule/save", schedule: { ...plain, enabled: el.checked } }, el.checked ? `${s.name} turned on` : `${s.name} turned off`);
      }
      return;
    }
    if (ds.person !== undefined && this._accessDraft) {
      if (el.checked) this._accessDraft.ids.add(ds.person);
      else this._accessDraft.ids.delete(ds.person);
      this._notes.access = "";
      this._render();
      return;
    }
    const d = this._schedEdit;
    if (d && ds.sday !== undefined) {
      const day = Number(ds.sday);
      d.days = el.checked ? [...new Set([...d.days, day])] : d.days.filter((x) => x !== day);
      return;
    }
    if (d && ds.s) {
      const key = ds.s;
      const value = el.type === "checkbox" ? el.checked : el.value;
      d[key] = value;
      if (key === "play_kind") d.play_value = "";
      // Redraw where the form's shape changes.
      if (["hasStart", "hasStop", "play_kind", "setVolume", "limitVolume"].includes(key)) this._render();
    }
  }

  _onInput(ev) {
    const el = ev.target;
    if (el.id === "lib-search") {
      clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => {
        this._libQuery = el.value.trim();
        this._focusSearch = true;
        this._render();
      }, 300);
      return;
    }
    if (el.id === "max_volume") {
      const out = this.shadowRoot.getElementById("max_volume_out");
      if (out) out.textContent = Number(el.value) >= 100 ? "No cap" : `${el.value}%`;
      return;
    }
    if (el.dataset.volume) {
      const out = el.closest(".vol")?.querySelector("output");
      if (out) out.textContent = `${el.value}%`;
      return;
    }
    if (this._schedEdit && el.dataset.s && el.type !== "checkbox" && el.type !== "radio") {
      this._schedEdit[el.dataset.s] = el.value;
    }
    if (el.closest("#listening")) this._notes.listening = "";
  }

  async _onSubmit(ev) {
    const form = ev.target;
    ev.preventDefault();
    if (form.id === "access") return this._saveAccess();
    if (form.id === "add-speaker") {
      const entityId = this.shadowRoot.getElementById("new-speaker")?.value;
      if (!entityId) return;
      const name = this._candidates?.find((c) => c.entity_id === entityId)?.name || entityId;
      return this._speakerRequest({ type: "media_mgmt/speakers/add", entity_id: entityId }, () => `Added ${name}. Set its rules under Rules, or a bedtime schedule under Schedules.`);
    }
    if (form.id === "schedule") {
      this._syncSchedForm();
      return this._saveSchedule();
    }
    if (form.id === "add-rule") {
      const kind = this.shadowRoot.getElementById("rule-kind").value;
      const value = this.shadowRoot.getElementById("rule-value").value.trim();
      if (!value) return this._showError("Type what to block.");
      this._syncRules();
      return this._block(this._selected, kind, value, true);
    }
    this._syncRules();
    const d = this._draft;
    if (form.id === "listening") {
      const numbers = {};
      for (const [key, label, min, max] of [
        ["daily_budget", "Daily listening time", 0, 1440],
        ["warn_minutes", "Warn before time runs out", 0, 60],
        ["adult_mode_duration", "Adult mode lasts", 5, 720],
      ]) {
        const value = Number(d[key]);
        if (!Number.isInteger(value) || value < min || value > max) return this._showError(`${label} needs a whole number of minutes from ${min} to ${max}.`);
        numbers[key] = value;
      }
      if (d.windows.some((w) => !w.start || !w.end)) return this._showError("Give every quiet window a start and an end time, or remove it.");
      const quiet = d.windows.map((w) => `${w.start}-${w.end}${w.label.trim() ? ` ${w.label.trim().replace(/,/g, "")}` : ""}`).join(", ");
      return this._saveSettings("listening", { ...numbers, quiet_windows: quiet, limit_action: d.limit_action });
    }
    if (form.id === "filter-action") return this._saveSettings("filter_action", { filter_action: d.filter_action });
    if (form.id === "volume") return this._saveSettings("volume", { max_volume: Number(d.max_volume) });
    if (form.id === "warnings") {
      return this._saveSettings("warnings", { announce_tts: d.announce_tts || null, announce_on_player: !!d.announce_on_player, announce_players: d.announce_players || [] });
    }
  }
}

if (!customElements.get("media-mgmt-panel")) {
  customElements.define("media-mgmt-panel", MediaMgmtPanel);
}
