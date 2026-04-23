# topsongs for Jellyfin

`topsongs` creates Jellyfin music playlists from Last.fm top tracks. For each
eligible artist in a Jellyfin music library, it fetches that artist's
popularity-ranked Last.fm top tracks, matches those titles against local
Jellyfin tracks, and creates a `Top Songs - <Artist>` playlist for each target
Jellyfin user.

The tool is designed for scheduled container use, but it can also be run as a
local Python CLI during development or debugging.

## What It Does

For each target Jellyfin user, `topsongs`:

1. Reads visible artists and local audio tracks from Jellyfin.
2. Skips artists with `MIN_TRACKS_PER_ARTIST` or fewer local songs.
3. Fetches Last.fm top tracks for each eligible artist.
4. Matches Last.fm track titles conservatively against local Jellyfin tracks.
5. Creates a fresh `Top Songs - <Artist>` playlist in matched Last.fm rank order.
6. Removes an older playlist with the same name after the replacement is created.
7. Writes a compact run summary and detailed container logs.

The Jellyfin API key must be able to read users, read music items, create
playlists, and delete replaced playlists.

## Requirements

- Python 3.11 or newer for local runs
- Docker and Docker Compose for the recommended container setup
- A Jellyfin server with a music library
- A Jellyfin API key with sufficient playlist and user permissions
- A Last.fm API key

## Repository Layout

```text
top_songs/
  Dockerfile
  README.md
  LICENSE
  appdata/
    .env.example
    docker-compose.yml
    run-topsongs
  scripts/
    container-entrypoint.sh
  topsongs/
  tests/
```

## Configuration

Copy the example environment file and edit it for your Jellyfin and Last.fm
setup:

```bash
cd appdata
cp .env.example .env
```

Example values:

```env
JELLYFIN_URL=http://jellyfin:8096
JELLYFIN_API_KEY=replace_me
LASTFM_API_KEY=replace_me
MIN_TRACKS_PER_ARTIST=10
STATE_DIR=/app/state
LOG_LEVEL=INFO
REQUEST_TIMEOUT_SECONDS=20
REQUEST_MAX_RETRIES=2
RETRY_BACKOFF_SECONDS=1.0
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

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `JELLYFIN_URL` | yes | none | Base URL for the Jellyfin server, for example `http://jellyfin:8096`. |
| `JELLYFIN_API_KEY` | yes | none | Jellyfin API key used to read users/items and create/delete playlists. |
| `LASTFM_API_KEY` | yes | none | Last.fm API key used to fetch artist top tracks. |
| `MIN_TRACKS_PER_ARTIST` | no | `10` | Artists must have more local tracks than this value to be processed. |
| `STATE_DIR` | no | `/app/state` | Directory for runtime files such as `last_run.txt` and the lockfile. |
| `LOG_LEVEL` | no | `INFO` | Python logging level. Use `DEBUG` for request-level troubleshooting. |
| `REQUEST_TIMEOUT_SECONDS` | no | `20` | HTTP timeout for Jellyfin and Last.fm requests. |
| `REQUEST_MAX_RETRIES` | no | `2` | Retry count for retryable network and server errors. |
| `RETRY_BACKOFF_SECONDS` | no | `1.0` | Base delay between retries. |
| `ARTIST_ALLOWLIST` | no | empty | Comma-separated artist names to include. Empty means all artists. |
| `ARTIST_DENYLIST` | no | empty | Comma-separated artist names to exclude. |
| `USER_ALLOWLIST` | no | empty | Comma-separated Jellyfin user names to include. Empty means all enabled users. |
| `USER_DENYLIST` | no | empty | Comma-separated Jellyfin user names to exclude. |
| `LIBRARY_PATH_ALLOWLIST` | no | empty | Comma-separated Jellyfin `Path` prefixes to include, for example `/music`. |
| `LIBRARY_PATH_DENYLIST` | no | empty | Comma-separated Jellyfin `Path` prefixes to exclude. |
| `PROJECT_ROOT` | no | `..` | Docker build context used by `appdata/docker-compose.yml`. |
| `CRON_SCHEDULE` | no | `0 3 * * *` | Cron expression for scheduled container runs. The default runs daily at 03:00 in the container's local timezone. |
| `RUN_ON_STARTUP` | no | `false` | Set to `true` to run once when the container starts. |

Empty allowlist and denylist variables are valid and mean "no filter".

Allowlist and denylist examples:

```env
ARTIST_ALLOWLIST=Powerwolf,Nightwish
ARTIST_DENYLIST=Various Artists,Soundtrack
USER_ALLOWLIST=alice,bob
USER_DENYLIST=guest
LIBRARY_PATH_ALLOWLIST=/music
LIBRARY_PATH_DENYLIST=/music/podcasts,/music/audiobooks
```

Create API keys:

- Jellyfin: sign in as an administrator, open the Jellyfin dashboard, then go to
  `Advanced` > `API Keys` and create a new key for `topsongs`.
- Last.fm: open the [Last.fm API page](https://www.last.fm/api), choose
  `Get an API account`, create an API account, and copy the generated API key
  into `LASTFM_API_KEY`.

## Docker Compose

The recommended setup is Docker Compose from the `appdata/` directory:

```bash
cd appdata
cp .env.example .env
# edit .env
docker compose up -d --build
```

The container stays running and starts cron in the foreground. It runs on
`CRON_SCHEDULE`; set `RUN_ON_STARTUP=true` for an immediate run after startup.

To run a playlist refresh manually without waiting for cron:

```bash
./run-topsongs
```

To inspect logs:

```bash
cd appdata
docker compose logs -f app
```

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
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

## Runtime Files and Logs

`topsongs` writes a compact summary to:

```text
STATE_DIR/last_run.txt
```

The summary contains start and finish times, provider name, user and artist
counts, playlist counts, and failure counts. Parallel runs are prevented by a
lockfile in `STATE_DIR`.

Detailed output is written to container logs, including the ordered track list
for each applied playlist.

## Scripts and Runtime Files

- `Dockerfile` builds the Python package, installs cron, and sets the container
  entrypoint.
- `appdata/docker-compose.yml` is an example Compose setup for running the tool
  as a long-lived scheduled container. It loads `appdata/.env`, mounts
  `appdata/state` to `/app/state`, and builds from `PROJECT_ROOT`.
- `appdata/run-topsongs` runs one manual refresh inside the already-running
  Compose container. Use it for first-run checks, debugging, or one-off updates.
- `scripts/container-entrypoint.sh` is used inside the container. It exports the
  configured environment for cron, installs the cron schedule, optionally runs
  once on startup, and keeps cron running in the foreground.
- `appdata/.env.example` is a template only. Copy it to `appdata/.env`; never
  commit real credentials.

## Security and Privacy

Do not publish real `.env` files, state directories, or container logs without
reviewing them first.

Sensitive or private data may appear in:

- `JELLYFIN_API_KEY` and `LASTFM_API_KEY`
- Jellyfin user names and user IDs
- private Jellyfin server URLs or hostnames
- artist, track, album, and playlist names from your library
- Jellyfin item IDs in debug or error output

If an API key is accidentally published, revoke or rotate it before continuing
to use the project publicly.

## Current Scope

- No direct music library filesystem access is required.
- Matching is intentionally conservative.
- Playlist replacement is create-new then remove-old, not in-place mutation.
