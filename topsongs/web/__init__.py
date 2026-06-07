"""topsongs web UI — a small FastAPI dashboard that drives every topsongs action.

Serves a single-page dashboard and a JSON/SSE API over the same code the CLIs
use: status of the last run, the live Jellyfin playlists, a streamed playlist
refresh, the missing-songs gap report, and the purge/prune cleanups. Launched by
the ``topsongs-web`` console script and run alongside cron in the container.
"""
