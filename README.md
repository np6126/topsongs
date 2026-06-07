<div align="center">

<img src="docs/topsongs-logo.svg" alt="topsongs" width="420">

# topsongs for Jellyfin

### Per-artist "greatest hits" playlists for your Jellyfin library — built automatically, personalized per user, and refreshed on every scheduled run.

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

</div>

A Jellyfin music library knows your artists but has no "best of this artist" playlists, and Jellyfin will not generate them for you. `topsongs` fills that gap. For every artist you own enough tracks of, it builds a `Top Songs - <Artist>` playlist ordered by Last.fm's crowd-sourced popularity, then nudges that order toward what each Jellyfin user actually plays. It runs unattended on a nightly schedule; each run re-reads your library and refreshes every playlist to match — no manual curation, no playlist housekeeping.

## Highlights

- **Non-destructive.** `topsongs` only creates and deletes playlists. It never downloads music, modifies tracks, tags, files, or albums — your library is left exactly as it was.
- **Scoped, predictable cleanup.** It only deletes playlists whose name starts with the prefix you configure. Everything else in Jellyfin — including playlists you made by hand — is invisible to it.
- **Safe to preview.** `DRY_RUN=true` runs a full planning pass and logs every action it would take, while writing nothing to Jellyfin.
- **Failure isolation.** One artist's failure does not abort the rest of the run, and the failed artist's existing playlist is kept — a transient Last.fm hiccup never costs you data.
- **Personalized per user.** Each Jellyfin user gets their own playlists, reordered by their own play counts and favorites — not one shared ranking.
- **Conservative matching.** Track titles are matched exactly first, then by a normalized form (lowercased, accent-folded, remaster/live/feat. tags stripped). It is deliberately not fuzzy, so it does not invent matches — and it is not a recommendation engine.
- **Container-first, self-hostable.** Ships as a Docker image with a Compose example and a nightly cron. It is also a plain Python CLI for development and one-off runs.
- **Web dashboard.** An optional built-in UI drives every action — trigger a run with a live log stream, browse the live playlists, run the missing-songs report, and preview/execute purge and prune — alongside the nightly cron in the same container.

---

## Quick start

You need a Jellyfin server with a music library, a Jellyfin API key, and a Last.fm API key. [Creating the API keys](#creating-api-keys) is covered below.

The recommended setup is Docker Compose from the `appdata/` directory:

```bash
cd appdata
cp .env.example .env
# edit .env — set JELLYFIN_URL, JELLYFIN_API_KEY, LASTFM_API_KEY
docker compose up -d --build
```

The container stays running and starts cron in the foreground. It runs on `CRON_SCHEDULE` (daily at 03:00 by default). To trigger a run immediately at startup, set `RUN_ON_STARTUP=true`.

To run a refresh now, without waiting for cron:

```bash
./run-topsongs
```

To watch the logs:

```bash
docker compose logs -f app
```

> [!TIP]
> Want to see what a run would do before it touches Jellyfin? Set `DRY_RUN=true` in `.env` and run `./run-topsongs` — every planned action is logged and nothing is written.

## Web dashboard

<div align="center">
<img src="docs/screenshot-dashboard.png" alt="topsongs dashboard: last run, counts, next schedule and mode at a glance" width="49%">
&nbsp;
<img src="docs/screenshot-missing.png" alt="missing-songs report with per-album coverage bars" width="49%">
<br>
<sub><em>The dashboard (left) and the missing-songs report (right).</em></sub>
</div>

The container also serves a web dashboard on port `8080` (the `appdata/docker-compose.yml` example publishes it). Open `http://<host>:8080` and you get every topsongs action in one place:

- **Dashboard** — the last run's status and counts, the next scheduled run, the run-lock state, and Jellyfin reachability at a glance.
- **Run** — trigger a playlist refresh (with an optional dry run) and watch the logs stream live; it is the same job cron runs nightly, and the run lock still prevents overlap.
- **Playlists** — the managed playlists currently in Jellyfin, grouped per user (works in both prefix and tag mode).
- **Missing** — the [missing-songs gap report](#finding-missing-songs) rendered with per-album coverage bars.
- **Purge** and **Prune** — preview exactly what would be deleted, then execute behind a confirmation.
- **Config** — the effective settings of the running container (secrets are redacted).

It runs as a small FastAPI app started by the `topsongs-web` console script, in the same container as cron. The dashboard is unauthenticated by default, which is fine behind a reverse proxy or on a trusted network; set `TOPSONGS_WEB_TOKEN` to require that token (sent as a bearer token) on every API call. `TOPSONGS_WEB_HOST` and `TOPSONGS_WEB_PORT` change the bind address and port.

> [!WARNING]
> The dashboard can delete playlists (purge/prune) and trigger runs. Do not expose port `8080` to an untrusted network without setting `TOPSONGS_WEB_TOKEN` or putting an authenticating proxy in front of it.

For local development, install the web extra and launch it directly:

```bash
pip install -e '.[web]'
topsongs-web   # serves on 0.0.0.0:8080
```

## Personalized ranking

Playlists are built per Jellyfin user, so `topsongs` does not simply copy the Last.fm order. It also reads each user's own play counts and favorites from Jellyfin and lets them reorder the list, so songs a user actually listens to move higher.

`PERSONALIZATION_WEIGHT` controls how strongly personal listening counts:

| Value | Behavior |
| :---: | --- |
| `0.0` | Pure Last.fm order. |
| `0.6` (default) | Personal taste leads; Last.fm decides where the user has little listening history. |
| `1.0` | Order driven almost entirely by the user's own play counts and favorites. |

When `APPEND_UNMATCHED_SONGS` is enabled and `PERSONALIZATION_WEIGHT` is above `0.0`, the appended local tracks are ordered by play count as well.

## Configuration

All configuration is environment variables, loaded from `appdata/.env`. Copy `.env.example` to `.env` as shown in [Quick start](#quick-start), then edit it for your setup.

Example values:

```env
JELLYFIN_URL=http://jellyfin:8096
JELLYFIN_API_KEY=replace_me
LASTFM_API_KEY=replace_me
MIN_TRACKS_PER_ARTIST=10
MIN_TRACK_DURATION_SECONDS=60
STATE_DIR=./state
LOG_LEVEL=INFO
REQUEST_TIMEOUT_SECONDS=20
REQUEST_MAX_RETRIES=2
RETRY_BACKOFF_SECONDS=1.0
RUN_CONCURRENCY=1
MIN_REQUEST_INTERVAL=0
MAX_PROVIDER_TRACKS=200
PERSONALIZATION_WEIGHT=0.6
PLAYLIST_NAME_PREFIX=Top Songs - 
APPEND_UNMATCHED_SONGS=true
DRY_RUN=false
ARTIST_ALLOWLIST=
ARTIST_DENYLIST=
USER_ALLOWLIST=
USER_DENYLIST=
LIBRARY_PATH_ALLOWLIST=
LIBRARY_PATH_DENYLIST=
PROJECT_ROOT=..
CRON_SCHEDULE=0 3 * * *
RUN_ON_STARTUP=false
```

`JELLYFIN_URL`, `JELLYFIN_API_KEY`, and `LASTFM_API_KEY` are required; everything else has a working default.

Characters invalid in filenames (`/ \ : * ? " < > |`) are replaced with `_` in the artist part of a playlist name, so `AC/DC` becomes `Top Songs - AC_DC`.

<details>
<summary><strong>Full configuration reference</strong></summary>
<br>

| Variable | Required | Default | Purpose |
| --- | :---: | --- | --- |
| `JELLYFIN_URL` | yes | none | Base URL for the Jellyfin server, for example `http://jellyfin:8096`. |
| `JELLYFIN_API_KEY` | yes | none | Jellyfin API key used to read users/items and create/delete playlists. |
| `LASTFM_API_KEY` | yes | none | Last.fm API key used to fetch artist top tracks. |
| `MIN_TRACKS_PER_ARTIST` | no | `10` | Artists must have more local tracks than this value to be processed. |
| `MIN_TRACK_DURATION_SECONDS` | no | `60` | Local tracks shorter than this are excluded from matching and playlists. Set to `0` to disable duration filtering. |
| `STATE_DIR` | no | `./state` | Directory for runtime files such as `last_run.txt` and the lockfile, relative to the working directory. |
| `LOG_LEVEL` | no | `INFO` | Python logging level. Raise to `DEBUG` for per-request and per-track detail. |
| `REQUEST_TIMEOUT_SECONDS` | no | `20` | HTTP timeout for Jellyfin and Last.fm requests. |
| `REQUEST_MAX_RETRIES` | no | `2` | Retry count for retryable network and server errors. |
| `RETRY_BACKOFF_SECONDS` | no | `1.0` | Base delay between retries. |
| `RUN_CONCURRENCY` | no | `1` | Number of artists planned in parallel per user. `1` keeps the sequential behavior; higher values process more artists at once, which can shorten a run when Last.fm fetches dominate. Clamped to `1`–`16`. |
| `MIN_REQUEST_INTERVAL` | no | `0` | Minimum seconds between Last.fm requests, enforced across all threads. `0` disables throttling; raise it if Last.fm returns HTTP 429 under concurrency. |
| `MAX_PROVIDER_TRACKS` | no | `200` | Maximum Last.fm top tracks to fetch and consider per artist. |
| `PERSONALIZATION_WEIGHT` | no | `0.6` | How much each user's own Jellyfin listening reorders a playlist, from `0.0` (pure Last.fm order) to `1.0` (purely personal). Clamped to `0.0`–`1.0`. See [Personalized ranking](#personalized-ranking). |
| `PLAYLIST_NAME_PREFIX` | no | `Top Songs - ` | Prefix used for managed playlist names such as `Top Songs - Powerwolf`. Only playlists with this prefix are considered managed and eligible for cleanup. Ignored when `PLAYLIST_TAG_MANAGED` is on. |
| `PLAYLIST_TAG_MANAGED` | no | `false` | When `true`, managed playlists are identified by a Jellyfin tag instead of the name prefix, so names can be bare (`Powerwolf` instead of `Top Songs - Powerwolf`). See [Tag-managed playlists](#tag-managed-playlists). |
| `PLAYLIST_MANAGED_TAG` | no | `topsongs` | The Jellyfin tag applied to, and used to recognize, managed playlists when `PLAYLIST_TAG_MANAGED` is on. |
| `APPEND_UNMATCHED_SONGS` | no | `true` | Whether local tracks missing from the provider top list are appended to the end of generated playlists, one entry per song. Set to `false` to keep playlists limited to provider matches. |
| `DRY_RUN` | no | `false` | Set to `true` to simulate a run without creating or deleting any playlists. All planned actions are logged but no changes are written to Jellyfin. |
| `ARTIST_ALLOWLIST` | no | empty | Comma-separated artist names to include. Empty means all artists. |
| `ARTIST_DENYLIST` | no | empty | Comma-separated artist names to exclude. |
| `USER_ALLOWLIST` | no | empty | Comma-separated Jellyfin user names to include. Empty means all enabled users. |
| `USER_DENYLIST` | no | empty | Comma-separated Jellyfin user names to exclude. |
| `LIBRARY_PATH_ALLOWLIST` | no | empty | Comma-separated Jellyfin `Path` prefixes to include, for example `/music`. |
| `LIBRARY_PATH_DENYLIST` | no | empty | Comma-separated Jellyfin `Path` prefixes to exclude. |
| `PROJECT_ROOT` | no | `..` | Docker build context used by `appdata/docker-compose.yml`. |
| `CRON_SCHEDULE` | no | `0 3 * * *` | Cron expression for scheduled container runs. The default runs daily at 03:00 in the container's local timezone. |
| `RUN_ON_STARTUP` | no | `false` | Set to `true` to run once when the container starts. |
| `TOPSONGS_WEB_HOST` | no | `0.0.0.0` | Bind address for the [web dashboard](#web-dashboard). |
| `TOPSONGS_WEB_PORT` | no | `8080` | Port for the web dashboard. |
| `TOPSONGS_WEB_TOKEN` | no | empty | When set, every dashboard API call must send this value as a bearer token. Empty leaves the dashboard open. |

</details>

### Tag-managed playlists

By default `topsongs` recognizes the playlists it manages by their name prefix (`Top Songs - `), which means every managed playlist carries that prefix in its name. If you would rather the playlists be named bare — just the artist, like `Powerwolf` — set `PLAYLIST_TAG_MANAGED=true`.

In tag mode, `topsongs` drops the prefix from new playlist names and instead applies a Jellyfin tag (`PLAYLIST_MANAGED_TAG`, default `topsongs`) to every playlist it creates. That tag, not the name, is what marks a playlist as managed: only tagged playlists are refreshed and eligible for cleanup, so a hand-made playlist that happens to share an artist name is left untouched.

```env
PLAYLIST_TAG_MANAGED=true
PLAYLIST_MANAGED_TAG=topsongs
```

> [!NOTE]
> The two modes track playlists differently, so switching `PLAYLIST_TAG_MANAGED` on an existing deployment orphans the playlists created under the old mode — they keep the old naming and are no longer recognized as managed. Clean them up first with [`topsongs-purge`](#bulk-playlist-cleanup) (prefix mode) before the switch.

### Allow and deny filters

Each of artist, user, and library-path has an allowlist and a denylist. Name matching is normalized; library-path matching compares against Jellyfin `Path` prefixes. An empty allowlist or denylist is valid and means "no filter".

```env
ARTIST_ALLOWLIST=Powerwolf,Nightwish
ARTIST_DENYLIST=Various Artists,Soundtrack
USER_ALLOWLIST=alice,bob
USER_DENYLIST=guest
LIBRARY_PATH_ALLOWLIST=/music
LIBRARY_PATH_DENYLIST=/music/podcasts,/music/audiobooks
```

### Creating API keys

- **Jellyfin:** sign in as an administrator, open the Jellyfin dashboard, then go to `Advanced` > `API Keys` and create a new key for `topsongs`.
- **Last.fm:** open the [Last.fm API page](https://www.last.fm/api), choose `Get an API account`, create an API account, and copy the generated API key into `LASTFM_API_KEY`.

### Updating a Compose deployment

`appdata/restart.py` pulls the latest code from git, rebuilds the image, and restarts the Compose container in one step. Run it from the `appdata/` directory:

```bash
cd appdata
python3 restart.py
```

## Finding missing songs

`topsongs-missing` is a companion gap report: it shows which tracks of an artist are absent from your Jellyfin library, grouped by album, as a structured colored console report (its output and `--help` text are in German). It compares the local library against the artist's Last.fm discography.

Check a single artist:

```bash
topsongs-missing "Metallica"
```

Check every artist in the library:

```bash
topsongs-missing
```

In a Docker Compose deployment, run it inside the container with the `appdata/topsongs-missing` wrapper, which forwards all arguments:

```bash
cd appdata
./topsongs-missing "Metallica"
```

| Option | Purpose |
| --- | --- |
| `--user <name>` | Jellyfin user whose library is inspected. Defaults to the first enabled user. |
| `--all-types` | Also include compilations and live albums. They are excluded by default; studio albums and EPs are always shown. |
| `--no-cache` | Ignore the cached discography and fetch fresh data from Last.fm. |

`topsongs-missing` reuses `JELLYFIN_URL`, `JELLYFIN_API_KEY`, `LASTFM_API_KEY`, and the allowlist/denylist settings from the same configuration. A few specifics:

- Last.fm exposes no release-type or release-date metadata, so compilations and live albums are detected by name, and edition variants (`Deluxe`, `Remastered`, ...) are merged.
- Last.fm's crowd-sourced data sometimes contains misspelled duplicates, so a track that differs from one you own by a single-character typo is still counted as owned. This typo tolerance applies only to the gap report, not to playlist generation.
- Fetched discographies are cached on disk under `STATE_DIR/discography_cache/` with a 30-day TTL, to keep repeated runs fast and easy on the Last.fm API.

## Bulk playlist cleanup

A normal run already deletes the managed playlists that no longer apply. Two companion commands handle the larger, manual cleanups — both act across **all** Jellyfin users, both print a plan first, and both ask for confirmation unless `--yes` is given (or preview only with `--dry-run`). The same actions are available in the [web dashboard](#web-dashboard).

**`topsongs-purge`** deletes every playlist whose name starts with a prefix — by default the configured `PLAYLIST_NAME_PREFIX`, or a different one via `--prefix`. It refuses an empty prefix, which would match every playlist. Use it to remove all `topsongs`-created playlists at once, for example before [switching to tag-managed mode](#tag-managed-playlists).

```bash
topsongs-purge --dry-run
topsongs-purge --prefix "Top Songs - " --yes
```

**`topsongs-prune`** is the inverse: it keeps a named allowlist and deletes everything else. `--keep` is required (an empty allowlist would wipe every playlist) and takes repeated or comma-separated names. Kept playlists can optionally be renamed with `--rename-prefix`; matching ignores that prefix, so re-runs are idempotent.

```bash
topsongs-prune --keep Alice --keep Bob --dry-run
topsongs-prune --keep Alice,Bob --rename-prefix _ --yes
```

In a Docker Compose deployment, run them inside the container with the `appdata/topsongs-purge` and `appdata/topsongs-prune` wrappers, which forward all arguments.

## Local development

`topsongs` is container-first, but it is also a plain Python CLI. Local runs need Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

`topsongs` reads its configuration from `appdata/.env`. Create it first (see [Configuration](#configuration)), then run a refresh:

```bash
topsongs
```

Run tests and lint checks:

```bash
pytest
ruff check .
```

Build the Docker image from the repository root:

```bash
docker build -t topsongs:dev .
```

The console entry points are `topsongs` (also `run-topsongs`) for a playlist run, `topsongs-missing` for the [gap report](#finding-missing-songs), `topsongs-purge` and `topsongs-prune` for [bulk cleanup](#bulk-playlist-cleanup), and `topsongs-web` for the [web dashboard](#web-dashboard).

## Runtime files and logs

Docker Compose mounts `appdata/state` to `/app/state`. The state directory holds the run summary, the lockfile, and the `topsongs-missing` discography cache.

**Run summary.** Each playlist run writes a compact summary to `STATE_DIR/last_run.txt` with start and finish times, user/artist/playlist/failure counts, and two local-track counts: `unmatched_local_track_count` (tracks the provider's top list does not cover) and `duplicate_local_track_count` (tracks dropped because another edition of the same song is already included).

**Lockfile.** A lockfile in `STATE_DIR` prevents overlapping runs; a second run exits cleanly. Locks older than two hours are cleared automatically.

**Logs.** At the default `INFO` level, container logs carry one `event=…` summary line per user, artist, and applied playlist. Set `LOG_LEVEL=DEBUG` to also log every HTTP request and the full ordered track list of each playlist.

## Security and privacy

API keys are stored in a plain `.env` file.

> [!WARNING]
> Do not publish real `.env` files, state directories, or container logs without reviewing them first.

Sensitive or private data may appear in:

- `JELLYFIN_API_KEY` and `LASTFM_API_KEY`
- Jellyfin user names and user IDs
- private Jellyfin server URLs or hostnames
- artist, track, album, and playlist names from your library
- Jellyfin item IDs in debug or error output

> [!IMPORTANT]
> If an API key is accidentally published, revoke or rotate it before continuing to use the project publicly.

## License

`topsongs` is released under the [Apache-2.0](LICENSE) license. Current version: 0.2.1.
