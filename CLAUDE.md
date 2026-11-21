# Media Mgmt: notes for Claude and other coding agents

Media Mgmt is a HACS custom integration (`custom_components/media_mgmt`, domain `media_mgmt`) that adds parental controls, schedules and analytics to any Home Assistant `media_player`. It's the music companion to [TV Mgmt](https://github.com/bisman-automations/ha-tv-mgmt) and follows the same structure and style. When in doubt, do what TV Mgmt does.

The sidebar app is the product. Every setting must be manageable there, not only in the config/options flow.

## Layout

| Path | What it is |
| --- | --- |
| `manager.py` | `MediaManager`, one per speaker (config entry). Counts listening, makes decisions, enforces limits, filters, volume caps, sleep timers and schedules. |
| `player.py` | Reads the speaker's state and sends it commands, with fallbacks (skip → pause → stop → turn off) for what the speaker supports. |
| `ma_link.py`, `playback.py` | Finds the speaker's Music Assistant player (`resolve`), and plays an artist, album, song or playlist through it or the fallbacks. While the Music Assistant player plays, `player.target` is that player and every read and command goes to it. |
| `targets.py`, `saved.py`, `intent.py`, `llm.py` | Playing an artist on request: which speaker (`find_speaker`), the home's saved artists, the `MediaMgmtPlayArtist` intent and the AI assistant tool. `blueprints/automation/media_mgmt/play_artist.yaml` is the text and voice blueprint. |
| `state.py`, `quiet.py`, `schedules.py`, `filters.py`, `media.py`, `activity.py`, `artists.py`, `home.py`, `live_view.py` | **Pure modules: no Home Assistant imports.** Unit-tested standalone through `tests/conftest.py`. Keep them pure. |
| `home_limits.py` | `HomeLimits`: the whole home's limits and weekly summary, one for all speakers (stored in `media_mgmt.home`, not in any config entry), ported from TV Mgmt. Adds up each counted speaker's `used_seconds`, gives each speaker the home's time left (`decide(home_remaining=...)`), notifies, and makes every speaker re-decide when the home's time runs out. The Sunday 18:00 summary listener runs only while a speaker is registered, so tests don't leave a timer. |
| `live_activity.py` | A speaker's Live Activity on phones (1.6.0: `live_view(song=describe(player.media))` makes the song the message while the music may carry on; `LiveView.song` is compared, so a new song pushes) (`CONF_LIVE_ACTIVITY`, in the announcements section), ported from TV Mgmt: shown while music plays, pushed only when `live_view` changes, "Music off" then cleared a minute after the music stops. `manager.notify()` calls `refresh()`. |
| `storage.py` | `ProfileState` (today's counters and controls), the activity log, and schedules, each in its own `Store`. |
| `websocket.py` | The sidebar app's API (`media_mgmt/*` commands). |
| `frontend/media-mgmt-panel.js` | The sidebar app: one plain web component, **no build step**. |
| `panel.py`, `access.py` | Sidebar registration, and who may use it (admins plus parents an admin picks). |
| `config_flow.py` | Adds a speaker. The options flow mirrors the sidebar app's Rules tab. `async_step_reconfigure` (1.7.0) changes the speaker with `async_update_and_abort`; the update listener reloads. |
| `references.py`, `repairs.py` | (1.7.0) The entity IDs a profile stores (`referenced_ids`: the speaker in `entry.data`, the Music Assistant player, the warning voice and speakers in options). A renamed one is followed (`async_follow_rename`: data, unique ID unless another profile has it, options). A deleted speaker or Music Assistant player raises a fixable repair issue (`speaker_missing_<entry_id>`, `music_assistant_player_missing_<entry_id>`, translations under `issues`), checked once Home Assistant is running and on registry and state add/remove events; "missing" means neither the registry nor the states know it, so unavailable isn't missing. Issues are deleted on unload and removal. `repairs.py` holds the fix flows. |
| `schema.py` | The only place that imports the schema library: always `from .schema import vol` (probatio on 2026.10+, voluptuous before), so mypy checks against what Home Assistant uses. |
| `entity.py`, `sensor.py`, `switch.py`, `select.py`, `button.py` | Entities, all on one service device per speaker. |
| `docs/logo.svg` | Source of the logo. `python scripts/make_brand.py` renders `brand/*.png` and `docs/logo.png`. |

## Rules that keep it working

- **Bedtime fade** (`CONF_BEDTIME_FADE`, minutes): `_check_bedtime_fade` starts a fade (`reason: bedtime`) when `seconds_until_stop()` (quiet window start or listening time left) is within it, stops fading once the music is blocked and restores the volume after the stop (`_async_stop_music`), and cancels with the volume restored when extra time pushes the stop back.
- **Quiet ticks** (1.5.4): `_on_tick`, and since 1.7.0 `_on_player_update` (a play position update), call `_notify_if_changed()`, which calls `notify()` only when `_tick_fingerprint()` (repr of `state`, the decision, the Music Assistant link and its player's state and name, `player.target`, the player's availability, power, state, media, volume and features, and the next schedule runs) changed (`_tick_seen`, also set by `notify()` and at the end of setup); something new that a tick or a speaker update changes and an entity or the panel shows goes in the fingerprint. An unlinked speaker retries `resolve_ma_link` on a tick at most every `MA_RETRY`; the entity registry listener has `event_filter=_media_player_change`, the device registry one `_device_change` (`_DEVICE_FIELDS`: name, name_by_user, area, connections). Entities (1.7.0) write on `SIGNAL_UPDATED` only when `_shown()` (available, state, capability and extra attributes) differs from their last write or another write replaced their state (`_written`), as in TV Mgmt. The panel waits while `pageHidden()`. 1.7.1: `Player._track` drops state changes where only `UNREAD_ATTRIBUTES` (play position, its time, `entity_picture`) moved (`only_unread_changed`); an attribute Media Mgmt starts reading must not be in that set. The Live Activity's 15-minute restart timer runs only while an activity is showing (armed in `_push`, stopped in `_clear`).
- **Settings apply live, without reloading.** The update listener calls `MediaManager.apply_options()`. The one exception: when `entry.data["media_player"]` no longer matches `manager.entity_id` (Reconfigure, the speaker repair, a followed rename), the listener schedules the reload itself, as Home Assistant expects. Don't reload the entry for settings, and never pair an update listener with reloading methods in a config flow (`async_update_reload_and_abort`, or `_abort_if_unique_id_configured(updates=...)`): that's an error from Home Assistant 2026.12.
- **Schedules live in their own `Store`, not in options**, so editing them never touches the config entry.
- **Stored data must stay backward compatible.** New `ProfileState` fields need defaults, since unknown keys are dropped on load. New schedule fields must default so that schedules saved by older versions load unchanged (`load_schedules` skips anything that no longer validates, which would silently delete a user's schedule).
- **Support Home Assistant 2026.8 and newer** (`hacs.json`). The profile's device shares the speaker's identifiers, so they show as linked devices. Never pass `via_device` (removed in 2027.8), never read `DeviceEntry.config_entries`, and don't add the profile to the speaker's device. Newer APIs (such as `ToolAnnotations` for the AI tool, 2026.10) are imported with a fallback. `DeviceInfo` is a dataclass from 2026.11: build it with keyword arguments, never as a dict.
- **Access checks:** every websocket command uses `@require_access`, admin-only ones (speakers, access) use `require_admin`, and entity actions and services call `async_ensure_allowed`. Automations (no user) are always allowed. Playing an artist (`play_artist`, the intent, the Play artist select and buttons) is deliberately open to everyone, like pressing play; the rules still decide. Changing saved artists needs access.
- **Panel:** escape everything with `esc()`. Wrap every `localStorage` use in try/catch. Keep using Home Assistant's theme variables so it works in light and dark mode. Check it at phone width (390px) as well as desktop.
- `strings.json` and `translations/en.json` must be identical.

## Testing

Run the shared checks at the end of this file on both the oldest supported Home Assistant (`requirements_test_min.txt`, 2026.8) and the newest (`requirements_test.txt`). Both need Python 3.14. CI runs both.

- Treat any `Detected that custom integration 'media_mgmt' ...` warning in the output as a bug to fix, even if tests pass.
- `tests/test_logic.py` covers the pure modules; `tests/ha/` runs inside Home Assistant.
- `tests/ha/test_blocking_io.py` fails on any file access on the event loop from this package (`open`, `os.stat`/`lstat`, `Path.resolve`/`read_text`...), through setup with the sidebar panel, the websocket API, diagnostics, the flows and unload. It needs `home-assistant-frontend` (CI: `core-requirements: frontend`). Do file work with `hass.async_add_executor_job`.
- `tests/test_panel_frontend.mjs` (`node --test tests/*.mjs`) renders every tab of the sidebar app with a stub DOM, from `tests/fixtures/panel_ws.json`. `tests/ha/test_panel_fixture.py` fails when a websocket command's answer changes shape; write the file again with `MEDIA_MGMT_WRITE_FIXTURE=1 pytest tests/ha/test_panel_fixture.py`.
- CI's lint job runs `mypy custom_components/media_mgmt` (settings in `pyproject.toml`); keep it clean.
- Diagnostics: `diagnostics.TO_REDACT` plus `scrub_urls` (the query string of every web address). Anything new that names a person, a phone or a token goes in `TO_REDACT`, with a test in `tests/ha/test_diagnostics.py`.
- Under a frozen clock (`freezer.move_to`), `hass_ws_client` logins fail. In those tests call `websocket.profile_summary()` directly.
- Allow a few seconds' slack in timing assertions: the order Home Assistant fires timers in differs between versions.
- For UI changes, also run a real Home Assistant with the frontend (`pip install home-assistant-frontend==<the version in homeassistant/components/frontend/manifest.json>`, then `hass -c <config dir>` with this integration symlinked into `custom_components/`) and look at the panel in a browser.

## Writing

- User-facing text (README, CHANGELOG, panel, `strings.json`) is plain and short, written to a parent, not a developer. Say what happens, in the order it happens.
- **Never put the maintainer's own account details** (account numbers, service IDs, addresses, entity IDs from his home) in the README, docs, screenshots or tests. Use placeholders and sample data.
- Screenshots in `docs/images` use sample data and are taken at phone width.

<!-- BEGIN bisman-automations shared rules -->
<!-- This block is the same in every bisman-automations repo. Edit it in
     bisman-automations/.github (templates/CLAUDE.shared.md) and copy it to
     every repo; the Validate workflow's "standards" job checks it matches. -->

## Shared rules (every bisman-automations repo)

### Releases

- The version lives in `custom_components/<domain>/manifest.json`. Anything
  else that repeats it is called out in the repo-specific notes below and is
  bumped in the same commit.
- Versions follow [Semantic Versioning](https://semver.org): patch for fixes,
  translations, docs and CI; minor for new features, options or entities;
  major when something users rely on is removed or renamed (entities,
  services, events, options) or setup has to be redone.
- Check what is released before choosing a version:
  `git ls-remote --tags origin | awk -F/ '{print $3}' | sort -V | tail -1`
  (`sort -V`: plain sorting puts `v1.10.0` before `v1.9.0`). Never add
  changes to a released version. If the manifest version has no tag yet,
  add to its CHANGELOG section instead of bumping again.
- Every push to `main` ships as a release. In that same commit, named
  `Release X.Y.Z`, bump the manifest version and write the notes directly
  under a new `## [X.Y.Z] - YYYY-MM-DD` heading in `CHANGELOG.md` (Keep a
  Changelog: Added, Changed, Deprecated, Removed, Fixed, Security), with
  that version's compare link at the bottom. There is no `## [Unreleased]`
  section and no `[Unreleased]:` compare link. New work is not collected
  under a holding heading and moved later; the release commit is where the
  heading and the entries are written. The standards check fails if a
  `## [Unreleased]` heading is present.
- Ask Donavan before every push. Push fast-forward only: never force-push,
  rebase or amend anything already pushed, or rewrite history in any other
  way. Rewriting history orphans the release tags (it broke drafting in
  ha-button-actions).
- Pushing to `main` runs **Draft release**, which creates or refreshes a
  draft `vX.Y.Z` with that version's CHANGELOG section as the notes, the
  commits since the last release and `<domain>.zip`. **Donavan publishes
  the draft himself**, and publishing creates the tag. Never create or push
  tags, publish releases, or edit published releases.
- Publishing runs **Release check**: the tag must match the manifest version
  and the CHANGELOG, and be on `main`. If it fails, fix it with a new patch
  release, not by moving the tag.

### Commits

- Author commits as `Donavan Becker <donavan.becker@icloud.com>` (set
  `git config user.name` / `user.email` in the clone). HACS's
  default-repository check needs the submitter to have a fair share of the
  commits. Credit an AI assistant with a `Co-Authored-By:` trailer if you
  like, never as the author.
- Subject lines are plain, imperative and say what changed for the user
  ("Show Pico remotes as unavailable when Lutron isn't running"). No
  `fix:`/`feat:` prefixes. Release commits are "Release X.Y.Z".
- Commit and push only when asked.

### CI (shared workflows)

- `.github/workflows/` holds four thin callers of the reusable workflows in
  [bisman-automations/.github](https://github.com/bisman-automations/.github):
  `test.yml` (lint, frontend, pytest on the oldest supported and the newest
  Home Assistant, plus the upcoming one as information only), `validate.yml`
  (hassfest, HACS, standards), `draft-release.yml` and `release-check.yml`.
  Don't add jobs to the callers. Use the shared workflow's inputs, or change
  the shared workflow so every repo gets the improvement.
- `requirements_test.txt` leaves `pytest-homeassistant-custom-component`
  unpinned (newest Home Assistant) and pins ruff (and mypy where used).
  `requirements_test_min.txt` pins the harness release for the minimum in
  `hacs.json`: the newest harness release of that month. CI fails if they
  drift apart.
- Raising the minimum Home Assistant means changing, together: `hacs.json`,
  `requirements_test_min.txt`, `python-min` in `test.yml` (3.13 up to
  2026.2, 3.14 from 2026.3), the README's Home Assistant badge, and a
  CHANGELOG entry.
- Home Assistant 2026.3 and newer need Python 3.14 (3.14.2+).
- The published hassfest rejects `categories` in `manifest.json` and Pillow
  in `requirements`. Leave both out.
- Dependabot (`.github/dependabot.yml`) proposes action and pinned-tool
  updates weekly. It ignores the test harness on purpose.
- Test and Validate also run every Thursday, the day after Home Assistant's
  betas come out. The **next** test job (newest pre-release harness) is
  information only: when it fails, fix the cause before that release ships.

### Before saying work is done

Run from the repo root, in a Python 3.14 venv with `requirements_test.txt`
installed:

```
ruff check .
ruff format --check .
pytest
```

Also run `node --test tests/*.mjs` when the repo has Node tests, mypy when
the repo-specific notes list it, and the tests in a second venv with
`requirements_test_min.txt` when a change could behave differently on the
oldest supported Home Assistant. The standards check (also in CI) is
`python <path to bisman-automations/.github>/scripts/check_repo.py .`.

### Code and docs

- Support every Home Assistant from the `hacs.json` minimum to the newest
  release. Check for deprecations in the newest release and the beta.
- Keep entity IDs, unique IDs, service names and event names stable. When
  one has to change, migrate it and say so under Changed in the CHANGELOG.
- `strings.json` and `translations/en.json` hold the same keys. Home
  Assistant reads only `translations/`, so change both in the same commit.
- Never put personal details in the repo (README, CHANGELOG, code, tests,
  screenshots): no names, addresses, account or device identifiers, or real
  entity IDs. Use placeholders such as `light.living_room`.
- `README.md` is user documentation with the standard header (badges, HACS
  and "add integration" My buttons) and sections Installation, Setup, ...,
  Troubleshooting, Development, License. Use plain language and show names,
  not entity IDs, wherever the UI does.
<!-- END bisman-automations shared rules -->
