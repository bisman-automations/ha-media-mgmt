# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.1] - 2026-10-30

### Changed

- **Install from the Marketplace.** The README now explains how to install from the Marketplace that replaces HACS in Home Assistant 2026.11, with its own button. The HACS steps stay for Home Assistant 2026.10 and older, and an install you already have moves over by itself.

## [1.3.0] - 2026-10-30

### Changed

- **Requires Home Assistant 2026.8 or newer.** The older way of showing the profile under the speaker's device is gone; the profile shows under the speaker's **Linked devices**.
- The README follows the same layout as the other bisman-automations integrations: a button that opens it in HACS, a button that starts setup, and troubleshooting steps for debug logs and diagnostics.
- Each release now includes `media_mgmt.zip` for installing without HACS.
- The changelog no longer keeps an Unreleased section, and the agent notes follow the updated shared release rules.

### Fixed

- **AI assistants get the "play an artist" tool on Home Assistant 2026.8 and 2026.9.** It only loaded on 2026.10 and newer.

### Security

- **Diagnostics leave out picture links and announcement speakers.** A speaker's cover art link carries an access token, which used to be included in the file.

## [1.2.0] - 2026-10-26

### Added

- **Play an artist by name,** on any speaker Media Mgmt manages: "play Brahms on the kids room". It plays through Music Assistant when the speaker has a Music Assistant player, so any artist on your music services works, on Sonos, HomePod and Music Assistant speakers alike. See [Playing an artist](README.md#playing-an-artist).
  - **The `media_mgmt.play_artist` action** finds the speaker by profile, entity, name or area, and returns what played or why it didn't. Options: artist radio, shuffle, volume, a URI, the type (artist, album, song, playlist) and how to queue it.
  - **A blueprint for text and voice** ([import it](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbisman-automations%2Fha-media-mgmt%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fmedia_mgmt%2Fplay_artist.yaml)): "play *artist* on *speaker*", or "play *artist*" for the speaker in the voice assistant's room. The reply says what's playing, or why not.
  - **A tool for AI assistants** (OpenAI, Google, Anthropic, Ollama and others with Control Home Assistant on), offered while a managed speaker is exposed to Assist.
  - **Artists** in the sidebar app: search Music Assistant, play a result, or save it. **Save** next to an artist in **Played music** too.
  - **Saved artists,** shared by every speaker, with other names to ask for them by, artist radio, and Music Assistant's exact match so the same artist plays every time.
  - **Play artist** select and **Play** *artist* buttons for dashboards. Both start turned off.
  - A `media_mgmt_play` event, and a line in the activity log, each time someone asks for an artist.
- **Finds each speaker's Music Assistant player** by its Sonos ID, a HomePod's AirPlay address, the Home Assistant entity Music Assistant made it from, its name, or its area. **Rules → Music Assistant** shows which one and how, and lets you pick one by hand. Diagnostics include it.

### Changed

- **The rules follow the music into Music Assistant.** While a speaker's Music Assistant player is playing, blocked music, limits, quiet windows, the volume cap, schedules and sleep timers act on that player.
- **Schedules play artists, albums, songs and playlists the same way,** through the speaker's Music Assistant player when it has one, then a Sonos favourite or link, then music played on it before. A HomePod without Music Assistant now says how to fix it instead of failing quietly.

## [1.1.0] - 2026-10-17

### Added

- **Loading placeholders in the sidebar app** ([#1](https://github.com/bisman-automations/ha-media-mgmt/issues/1)). While a page loads, it shows a softly shimmering outline of what's coming: speaker cards on the dashboard, totals and a chart on Analytics, and rows elsewhere. The shimmer stays still if your device is set to reduce motion, and screen readers announce what's loading.

## [1.0.0] - 2026-10-16

### Added

- **Volume limits:** a schedule that plays nothing and only limits the volume between two times, such as 20% from 6:00 to 8:00 on school mornings. Turning the speaker up past it turns it straight back down; nothing is started or stopped, and the daily limit and quiet windows still apply.
  - Add one with **Add volume limit** under **Schedules**, or pick **Only limit the volume** in any schedule.
  - It's on whenever the clock is inside its times, including right after it's saved or after Home Assistant restarts.
  - The dashboard shows it while it's on ("Early morning: volume up to 20% until 8:00 AM"), and the activity log notes when it starts and ends.
  - `media_mgmt_schedule` events have `limit_started` and `limit_ended` actions. `run_schedule` and **Play now** don't apply to it, since it has nothing to play.

## [0.3.0] - 2026-10-16

### Added

- **Limit the volume during a schedule.** Each schedule can have its own volume limit, such as 30% for bedtime music. While it plays, turning the speaker up past the limit turns it straight back down; when it stops, the speaker's usual cap is back. The starting volume never goes above the limit.
  - The dashboard shows the limit on the volume slider and in the speaker's details ("30% while Bedtime music plays"), and the activity log says when it turned the volume back down.
  - New schedules start with a 30% limit. Schedules you already have don't get one until you set it.

## [0.2.0] - 2026-10-16

### Changed

- **Speakers on the dashboard collapse to just the player,** and start collapsed: artwork, what's playing, progress, play/pause, skip and volume, with a line underneath showing listening time and any schedule or sleep timer. Tap it to open the rest. Each speaker you open stays open on that device.

### Fixed

- **Ready for Home Assistant 2027.8.** Media Mgmt no longer passes `via_device` for its device on Home Assistant 2026.8 and newer, which logged a deprecation warning from 2026.10.
- A schedule test could fail depending on the order Home Assistant runs timers in.
- The repository now has a license, which HACS requires.

## [0.1.0] - 2026-10-16

First release.

### Added

- **A profile for each speaker,** through the integration that already runs it: Sonos, HomePod and AirPlay, Google Cast, Music Assistant, Spotify, Alexa Media and any other media player.
- **Daily listening limit,** counting only time spent playing, with a warning before it runs out. When it runs out, the music is paused (or stopped, or the speaker turned off).
- **Quiet windows,** when music stays off, such as bedtime or school hours.
- **Blocked music:** songs, artists (including songs they're featured on), albums, apps and words in a title, skipped as soon as they start. Block anything that's played before with one tap.
- **Volume cap.**
- **Schedules:** start an artist, playlist, album, song, favourite or media ID at a set time on chosen days, set the volume, shuffle and repeat, then fade out and stop at a set time. Schedules play through the daily limit and quiet windows. A schedule with only a stop time is a nightly sleep timer.
- **Sleep timers** with an optional fade-out; the volume is put back afterwards.
- **Spoken warnings** on the speaker itself (as an announcement over the music) and on other speakers.
- **Logo** and brand icons, in the style of TV Mgmt's.
- **Analytics** for each speaker and all of them together: music per day, the hours music plays, songs played, top artists, songs, albums and apps.
- **A history of every song played** (the last 3000 per speaker), searchable, with play counts and time.
- **Sidebar app** to manage everything: dashboard, activity, analytics, played music, schedules, rules, speakers and access. Admins add and remove speakers from the app, without going to Settings.
- **Pick a bedtime artist from history.** The schedule editor lists the artists, albums and songs a speaker has played, most played first, to tap.
- **Access control:** admins, plus the parents an admin picks, may change Media Mgmt from the app, entities and actions.
- Entities: mode, music filter, adult mode, block this song and artist buttons, and sensors for enforcement state, listening time, time remaining, extra time, now playing, songs today, blocked today, sleep timer and next schedule.
- Actions: `grant_extension`, `force_block`, `unblock`, `reset_usage`, `block_media`, `unblock_media`, `set_sleep_timer`, `cancel_sleep_timer` and `run_schedule`.
- Events: `media_mgmt_media_blocked`, `media_mgmt_warning`, `media_mgmt_enforcement_changed` and `media_mgmt_schedule`.

[1.3.1]: https://github.com/bisman-automations/ha-media-mgmt/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/bisman-automations/ha-media-mgmt/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/bisman-automations/ha-media-mgmt/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/bisman-automations/ha-media-mgmt/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/bisman-automations/ha-media-mgmt/compare/v0.3.0...v1.0.0
[0.3.0]: https://github.com/bisman-automations/ha-media-mgmt/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/bisman-automations/ha-media-mgmt/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/bisman-automations/ha-media-mgmt/releases/tag/v0.1.0
