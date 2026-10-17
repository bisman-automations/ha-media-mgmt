# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/bisman-automations/ha-media-mgmt/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/bisman-automations/ha-media-mgmt/compare/v0.3.0...v1.0.0
[0.3.0]: https://github.com/bisman-automations/ha-media-mgmt/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/bisman-automations/ha-media-mgmt/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/bisman-automations/ha-media-mgmt/releases/tag/v0.1.0
