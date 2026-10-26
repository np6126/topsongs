# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-10-26

### Changed
- Skipped songs no longer rank higher. Jellyfin counts a play as soon as
  playback starts, so every skip counted as a play. Each run now reads
  Jellyfin's activity log and subtracts the playbacks that ended within 30
  seconds from the play counts. If the log cannot be read, the run uses the
  plain play counts.

### Fixed
- Counts of one read in the singular in the command-line output and the
  dashboard, e.g. `1 playlist`, `1 user`, `1 day ago`, instead of `1
  playlists`; German gets its singular forms too (`1 Playlist wird gelöscht`).

## [0.3.0] - 2026-10-22

### Added
- Live playlists for concert prep: `topsongs-live` and the dashboard's Live
  view turn setlist.fm setlists into a Jellyfin playlist from the library —
  one concert in its running order, or a mix of up to 20 concerts with the
  most-played songs first. Concerts can be the newest, picked by number or
  setlist.fm link, one per venue, or found by tour, year, venue, city and
  country; the dashboard autocompletes those filters and the artist. Songs
  played at fewer than `--min-share` of the concerts (default 50 %) are left
  out. Made on request only; nothing replaces or deletes a playlist. Needs
  `SETLISTFM_API_KEY`; `LIVE_PLAYLIST_PREFIX` (default `Live - `) shapes the
  names.
- Live playlists carry the Jellyfin tag `topsongs-live`; runs, purge and prune
  never touch them, and prune lists them as protected.
- Live playlists for several users at once: `topsongs-live --user a,b` or
  `--all-users`, and user chips in the dashboard, which remember the last
  choice in the browser. Each user gets a copy matched against their own
  library. `--public`, or the dashboard's public switch, makes one playlist
  that every user sees instead.
- `TOPSONGS_LANGUAGE` (`en` or `de`): the language of all command-line output
  and `--help`, the dashboard, and the description of new live playlists.
  Logs and `last_run.txt` stay English.

### Changed
- **Breaking:** the command-line tools and the dashboard speak English by
  default. Set `TOPSONGS_LANGUAGE=de` to keep the German texts.
- The dashboard's artist autocomplete suggests names that start with the
  typed text, ignoring case and accents, instead of every name containing it.
- Playlists are created with a JSON body instead of the query parameters
  newer Jellyfin versions deprecate.
- **Breaking:** the tag alone marks the playlists of the nightly run. Every
  run tags what it creates with `PLAYLIST_MANAGED_TAG` and recognizes its
  playlists by it, never by name. `PLAYLIST_NAME_PREFIX` only shapes the names
  and now defaults to none, so names are bare (`Powerwolf`). Upgrading:
  - from the old default prefix mode: a user without tagged playlists gets
    their untagged `Top Songs - …` playlists (or those with the configured
    prefix) tagged once on the next run. With the prefix unset they are then
    replaced by bare-named ones; set `PLAYLIST_NAME_PREFIX="Top Songs - "` to
    keep the old names.
  - from tag mode: remove `PLAYLIST_NAME_PREFIX` if it is set, or the names
    gain that prefix; `PLAYLIST_TAG_MANAGED` can go.
- `topsongs-purge` and the dashboard's Purge delete the playlists with
  `PLAYLIST_MANAGED_TAG` unless a prefix is given; live playlists never.
- Jellyfin and Last.fm requests honour a server's `Retry-After` on retryable
  errors (up to 10 s), as the setlist.fm requests do.
- The dashboard's mode card shows the tag and the name prefix.

### Removed
- `PLAYLIST_TAG_MANAGED`; a leftover setting is ignored.

### Fixed
- The dashboard's artist autocomplete never learned of artists added after
  its first use: its cache did not expire. It now refreshes after an hour and
  keeps the old list while Jellyfin is unreachable.
- In tag mode, `topsongs-purge` found none of the nightly playlists: it looked
  for the name prefix, which tag mode leaves out of the names.

## [0.2.6] - 2026-10-21

### Fixed
- One playlist per band when Jellyfin holds the band as two artists whose
  names differ only in case or punctuation, e.g. `Blackmore's Night` with a
  straight and with a typographic apostrophe after a metadata refresh. Both
  return the same tracks, so every user got two identical playlists. Now only
  the first artist gets one and the duplicate's old playlist is removed; the
  duplicate is logged as `event=artist_duplicate` and noted in the report.
  Look-alike names with other tracks, and artists that only share a duet
  album, still get their own playlists.

## [0.2.5] - 2026-10-16

### Added
- `RECENCY_BONUS`: new releases get a score bonus that fades out over three
  years, since all-time Last.fm and Jellyfin play counts otherwise keep a new
  album near the bottom of its artist's playlist. The year comes from the
  track's Jellyfin year tag. Off unless set; `appdata/.env.example` sets `0.3`.

## [0.2.4] - 2026-09-20

### Fixed
- `topsongs` / `run-topsongs` now parse their command line. The entry point
  previously ignored `sys.argv` entirely, so `topsongs --help` printed no help
  and instead started a full production run that replaced every playlist; any
  typo'd flag did the same, silently.

### Added
- `--dry-run` on `topsongs` / `run-topsongs`, overriding `DRY_RUN` from the
  configuration for a single invocation.

## [0.2.3] - 2026-09-19

### Fixed
- Jellyfin authentication now sends the API key in the
  `Authorization: MediaBrowser Token="..."` header instead of the legacy
  `X-Emby-Token` header, which Jellyfin 12 rejects with 401 — every API call
  failed against a Jellyfin 12 server. Verified against Jellyfin 10.9, 10.10,
  10.11, 12.0 and 12.1: the new header authenticates on all of them.

### Documentation
- Note the minimum supported server version (Jellyfin 10.9). Playlist creation
  fails on 10.8 and older, which return 415 for `POST /Playlists`.

## [0.2.2] - 2026-07-07

### Fixed
- Track matching no longer lets a live/remaster edition steal the studio
  take's provider rank. When Last.fm's title differed from the library only in
  casing (e.g. "Kings Of The Carnival Creation" vs "Kings of the Carnival
  Creation"), the case-sensitive exact match missed and the normalized fallback
  picked whichever edition Jellyfin happened to return first — often the live
  one — dropping the studio track entirely. Exact matching is now
  case-insensitive, and when several local editions collapse to one normalized
  title the studio take (shortest title) wins the rank.

### Changed
- The appended block now dedups only by exact title. Distinct editions of an
  included song (live, remaster, demo, ...) are kept as their own entries
  instead of being collapsed away, so owning a track never drops it from the
  playlist. Only a genuinely identical-titled copy is still deduped.

## [0.2.1] - 2026-06-07

### Fixed
- Tag-managed mode no longer leaks duplicate playlists. The create→tag→delete
  sequence was not atomic: if tagging a freshly created playlist failed, the
  playlist was left untagged and thus invisible to every later run — never
  replaced and never orphan-deleted — so a stale copy accumulated next to each
  regenerated playlist. A failed tag now rolls back the just-created playlist,
  leaving any existing tagged playlist untouched.

## [0.2.0] - 2026-06-07

### Added
- **Web dashboard** (`topsongs-web`): an optional FastAPI UI on port `8080`
  that drives every action — trigger a run with a live log stream, browse the
  managed playlists per user, run the missing-songs report with per-album
  coverage bars, and preview/execute purge and prune behind a confirmation. It
  runs alongside cron in the same container. Unauthenticated by default; set
  `TOPSONGS_WEB_TOKEN` to require a bearer token, and `TOPSONGS_WEB_HOST` /
  `TOPSONGS_WEB_PORT` to change the bind address.
- **`topsongs-purge`**: delete every managed playlist by name prefix across all
  Jellyfin users. Defaults to `PLAYLIST_NAME_PREFIX`, accepts `--prefix`, and
  refuses an empty prefix. Supports `--dry-run` and `--yes`.
- **`topsongs-prune`**: keep a named allowlist of playlists and delete the rest
  across all users, with an optional `--rename-prefix` for the kept ones.
  `--keep` is required, and matching ignores the rename prefix so re-runs are
  idempotent.
- **Tag-managed playlist mode**: set `PLAYLIST_TAG_MANAGED=true` to identify
  managed playlists by a Jellyfin tag (`PLAYLIST_MANAGED_TAG`, default
  `topsongs`) instead of the name prefix, allowing bare playlist names.
- Playlists personalized per user: each user's Jellyfin play counts and
  favorites reorder their playlists, weighted by `PERSONALIZATION_WEIGHT`.
- `topsongs-missing` gap report: which tracks of an artist are absent from the
  library, grouped by album.
- `DRY_RUN` preview mode.
- Configurable playlist name prefix (`PLAYLIST_NAME_PREFIX`) with scoped,
  prefix-based cleanup of orphaned playlists.
- `appdata/restart.py` helper to pull, rebuild, and restart a Compose
  deployment in one step.
- Dashboard screenshots in the README.

### Changed
- README documents the web dashboard, tag-managed mode, and the purge/prune
  cleanup commands.

## 0.1.0 - 2026-04-23

### Added
- Initial release: per-artist "Top Songs" playlists built from Last.fm top
  tracks and matched against a Jellyfin music library, one set per Jellyfin
  user.
- Container-first deployment with a Docker Compose example and a nightly cron;
  also runnable as a plain Python CLI.
- Allow/deny filters for artists, users, and library paths.

[0.3.1]: https://github.com/np6126/topsongs/releases/tag/v0.3.1
[0.3.0]: https://github.com/np6126/topsongs/releases/tag/v0.3.0
[0.2.6]: https://github.com/np6126/topsongs/releases/tag/v0.2.6
[0.2.5]: https://github.com/np6126/topsongs/releases/tag/v0.2.5
[0.2.4]: https://github.com/np6126/topsongs/releases/tag/v0.2.4
[0.2.3]: https://github.com/np6126/topsongs/releases/tag/v0.2.3
[0.2.2]: https://github.com/np6126/topsongs/releases/tag/v0.2.2
[0.2.1]: https://github.com/np6126/topsongs/releases/tag/v0.2.1
[0.2.0]: https://github.com/np6126/topsongs/releases/tag/v0.2.0
