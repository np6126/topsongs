# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.0]: https://github.com/np6126/topsongs/releases/tag/v0.2.0
[0.1.0]: https://github.com/np6126/topsongs/releases/tag/v0.1.0
