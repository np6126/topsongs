# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- `appdata/restart.py` helper to pull, rebuild, and restart a Compose
  deployment in one step.
- Dashboard screenshots in the README.

### Changed
- README documents the web dashboard, tag-managed mode, and the purge/prune
  cleanup commands.

## [0.1.0] - 2026-04-23

### Added
- Initial release: per-artist "Top Songs" playlists built from Last.fm top
  tracks, matched against a Jellyfin music library and personalized per user by
  play counts and favorites.
- `topsongs-missing` gap report: which tracks of an artist are absent from the
  library, grouped by album.
- Container-first deployment with a Docker Compose example and a nightly cron;
  also runnable as a plain Python CLI.
- Allow/deny filters for artists, users, and library paths; `DRY_RUN` preview
  mode; scoped, prefix-based playlist cleanup.

[0.2.3]: https://github.com/np6126/topsongs/releases/tag/v0.2.3
[0.2.2]: https://github.com/np6126/topsongs/releases/tag/v0.2.2
[0.2.1]: https://github.com/np6126/topsongs/releases/tag/v0.2.1
[0.2.0]: https://github.com/np6126/topsongs/releases/tag/v0.2.0
[0.1.0]: https://github.com/np6126/topsongs/releases/tag/v0.1.0
