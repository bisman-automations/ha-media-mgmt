# Media Mgmt: working on this repo

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

Run both suites. CI runs Python 3.13 (older Home Assistant, the pre-2026.8 device path) and 3.14 (newest Home Assistant):

```bash
pip install -r requirements_test.txt   # in a Python 3.13 and a Python 3.14 venv
pytest -q
```

- Treat any `Detected that custom integration 'media_mgmt' ...` warning in the output as a bug to fix, even if tests pass.
- `tests/test_logic.py` covers the pure modules; `tests/ha/` runs inside Home Assistant.
- Under a frozen clock (`freezer.move_to`), `hass_ws_client` logins fail. In those tests call `websocket.profile_summary()` directly.
- Allow a few seconds' slack in timing assertions: the order Home Assistant fires timers in differs between versions.
- For UI changes, also run a real Home Assistant with the frontend (`pip install home-assistant-frontend==<the version in homeassistant/components/frontend/manifest.json>`, then `hass -c <config dir>` with this integration symlinked into `custom_components/`) and look at the panel in a browser.

## Writing

- User-facing text (README, CHANGELOG, panel, `strings.json`) is plain and short, written to a parent, not a developer. Say what happens, in the order it happens.
- **Never put the maintainer's own account details** (account numbers, service IDs, addresses, entity IDs from his home) in the README, docs, screenshots or tests. Use placeholders and sample data.
- Screenshots in `docs/images` use sample data and are taken at phone width.

## Releasing

1. Bump `version` in `manifest.json` (semantic versioning).
2. Add a section to `CHANGELOG.md` (Keep a Changelog), with links at the bottom.
3. Update the README for anything a user would notice.
4. Push to `main`. `draft-release.yml` creates or updates a draft GitHub release for that version. The maintainer publishes it, which is what HACS users get.

`test.yml` (pytest on both Python versions) and `validate.yml` (hassfest and the HACS check) must pass. HACS also needs the repo's license, description and topics.
