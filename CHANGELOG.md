# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/bisman-automations/ha-media-mgmt/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/bisman-automations/ha-media-mgmt/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/bisman-automations/ha-media-mgmt/releases/tag/v0.1.0
