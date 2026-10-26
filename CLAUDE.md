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
| `state.py`, `quiet.py`, `schedules.py`, `filters.py`, `media.py`, `activity.py`, `artists.py` | **Pure modules: no Home Assistant imports.** Unit-tested standalone through `tests/conftest.py`. Keep them pure. |
| `storage.py` | `ProfileState` (today's counters and controls), the activity log, and schedules, each in its own `Store`. |
| `websocket.py` | The sidebar app's API (`media_mgmt/*` commands). |
| `frontend/media-mgmt-panel.js` | The sidebar app: one plain web component, **no build step**. |
| `panel.py`, `access.py` | Sidebar registration, and who may use it (admins plus parents an admin picks). |
| `config_flow.py` | Adds a speaker. The options flow mirrors the sidebar app's Rules tab. |
| `entity.py`, `sensor.py`, `switch.py`, `select.py`, `button.py` | Entities, all on one service device per speaker. |
| `docs/logo.svg` | Source of the logo. `python scripts/make_brand.py` renders `brand/*.png` and `docs/logo.png`. |

## Rules that keep it working

- **Settings apply live, without reloading.** The update listener calls `MediaManager.apply_options()`. Don't reload the entry in the listener, and never pair an update listener with reloading methods in a config flow (`async_update_reload_and_abort`, or `_abort_if_unique_id_configured(updates=...)`): that's an error from Home Assistant 2026.12.
- **Schedules live in their own `Store`, not in options**, so editing them never touches the config entry.
- **Stored data must stay backward compatible.** New `ProfileState` fields need defaults, since unknown keys are dropped on load. New schedule fields must default so that schedules saved by older versions load unchanged (`load_schedules` skips anything that no longer validates, which would silently delete a user's schedule).
- **Support Home Assistant 2026.3 and newer** (`hacs.json`). Device linking has two paths, chosen by `hasattr(registry, "async_get_devices")`: 2026.8+ links devices through shared identifiers, older versions use `via_device` and add the entry to the speaker's device. On 2026.8+ never pass `via_device` (removed in 2027.8) and never read `DeviceEntry.config_entries`. `DeviceInfo` is a dataclass from 2026.11: build it with keyword arguments, never as a dict.
- **Access checks:** every websocket command uses `@require_access`, admin-only ones (speakers, access) use `require_admin`, and entity actions and services call `async_ensure_allowed`. Automations (no user) are always allowed. Playing an artist (`play_artist`, the intent, the Play artist select and buttons) is deliberately open to everyone, like pressing play; the rules still decide. Changing saved artists needs access.
- **Panel:** escape everything with `esc()`. Wrap every `localStorage` use in try/catch. Keep using Home Assistant's theme variables so it works in light and dark mode. Check it at phone width (390px) as well as desktop.
- `strings.json` and `translations/en.json` must be identical.

## Testing

Run the shared checks at the end of this file on both the oldest supported Home Assistant (`requirements_test_min.txt`, 2026.3, which still takes the pre-2026.8 device path) and the newest (`requirements_test.txt`). Both need Python 3.14. CI runs both.

- Treat any `Detected that custom integration 'media_mgmt' ...` warning in the output as a bug to fix, even if tests pass.
- `tests/test_logic.py` covers the pure modules; `tests/ha/` runs inside Home Assistant.
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
- Every push to `main` ships as a release. In the same push: bump the
  manifest version, and add a dated `## [X.Y.Z] - YYYY-MM-DD` section to
  `CHANGELOG.md` (Keep a Changelog: Added, Changed, Deprecated, Removed,
  Fixed, Security) with its compare link at the bottom. Small follow-ups can
  collect under `## [Unreleased]` first; move them into the version section
  when you bump.
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
