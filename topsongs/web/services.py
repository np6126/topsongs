"""Business logic for the web API, built on the same code paths as the CLIs.

Every Jellyfin-touching operation here reuses the existing CLI helpers
(``purge_cli``, ``prune_cli``, ``missing_cli``) so the web UI and the command
line can never drift apart. The functions return plain dicts ready to be
serialised as JSON.
"""
from __future__ import annotations

import io
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone

from rich.console import Console

from .. import missing_cli, prune_cli, purge_cli
from ..config import Settings
from ..discography import DiscographyCache
from ..jellyfin import JellyfinClient
from ..models import AlbumGap, ArtistGap
from ..providers.lastfm import LastFmProvider

# Settings fields that must never be sent to the browser in clear text.
_SECRET_FIELDS = {"jellyfin_api_key", "lastfm_api_key"}

# A Console that renders nowhere — the reused CLI helpers print progress to it,
# but the web layer wants their return values, not their terminal output.
_QUIET = Console(file=io.StringIO(), quiet=True)


class ConfigError(RuntimeError):
    """Configuration is missing or invalid (e.g. no JELLYFIN_URL)."""


def get_settings() -> Settings:
    try:
        return Settings()
    except Exception as exc:  # noqa: BLE001 - turn pydantic errors into a clean message
        raise ConfigError(str(exc)) from exc


@contextmanager
def _jellyfin(settings: Settings, *, timeout: float | None = None):
    client = JellyfinClient(
        base_url=settings.jellyfin_url,
        api_key=settings.jellyfin_api_key,
        timeout_seconds=timeout if timeout is not None else settings.request_timeout_seconds,
        max_retries=settings.request_max_retries,
        retry_backoff_seconds=settings.retry_backoff_seconds,
    )
    try:
        yield client
    finally:
        client.close()


def _artist_cache_path(settings: Settings):
    return settings.state_dir / "artists_cache.json"


def _write_artist_cache(settings: Settings, names: list[str]) -> None:
    """Persist the artist list so the Missing-view autocomplete is instant."""
    try:
        path = _artist_cache_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(set(names))), encoding="utf-8")
    except OSError:
        pass  # autocomplete is non-critical; never fail a request over it


# --------------------------------------------------------------------------- #
# Status / config
# --------------------------------------------------------------------------- #

def status_payload() -> dict:
    try:
        settings = get_settings()
    except ConfigError as exc:
        return {"configured": False, "error": str(exc)}

    schedule = os.environ.get("CRON_SCHEDULE", "0 3 * * *")
    return {
        "configured": True,
        "jellyfin_url": settings.jellyfin_url,
        "prefix": settings.playlist_name_prefix,
        "tag_managed": settings.playlist_tag_managed,
        "managed_tag": settings.playlist_managed_tag,
        "dry_run_default": settings.dry_run,
        "personalization_weight": settings.personalization_weight,
        "cron_schedule": schedule,
        "next_run": _next_cron_run(schedule),
        "lock": _lock_status(settings),
        "last_run": _parse_last_run(settings),
        "jellyfin": _ping_jellyfin(settings),
    }


def _parse_last_run(settings: Settings) -> dict | None:
    from .runner import parse_last_run

    return parse_last_run(settings.state_dir)


def _lock_status(settings: Settings) -> dict:
    lock_path = settings.state_dir / ".run.lock"
    try:
        stat = lock_path.stat()
    except FileNotFoundError:
        return {"active": False}
    age = datetime.now(timezone.utc).timestamp() - stat.st_mtime
    pid = None
    try:
        pid = int(lock_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pass
    return {"active": True, "age_seconds": round(age), "stale": age > 7200, "pid": pid}


def _next_cron_run(schedule: str) -> dict | None:
    try:
        from croniter import croniter
    except ImportError:
        return None
    try:
        now = datetime.now().astimezone()
        nxt = croniter(schedule, now).get_next(datetime)
    except (ValueError, KeyError):
        return None
    return {
        "at": nxt.isoformat(),
        "seconds_until": max(0, round((nxt - now).total_seconds())),
    }


def _ping_jellyfin(settings: Settings) -> dict:
    try:
        with _jellyfin(settings, timeout=5.0) as client:
            users = client.get_users()
        return {"reachable": True, "user_count": len(users)}
    except Exception as exc:  # noqa: BLE001 - a dead server must not 500 the dashboard
        return {"reachable": False, "error": str(exc)}


def config_view() -> dict:
    settings = get_settings()
    fields = []
    for name, field in Settings.model_fields.items():
        alias = field.alias or name.upper()
        value = getattr(settings, name)
        secret = name in _SECRET_FIELDS
        if secret:
            display = "•••• (gesetzt)" if value else "(nicht gesetzt)"
        elif isinstance(value, list):
            display = ", ".join(value) if value else "—"
        elif isinstance(value, bool):
            display = "true" if value else "false"
        else:
            display = str(value)
        fields.append({"key": alias, "value": display, "secret": secret})
    return {"fields": fields}


# --------------------------------------------------------------------------- #
# Artists (autocomplete)
# --------------------------------------------------------------------------- #

def artist_names() -> dict:
    """Artist names for the Missing-view autocomplete.

    Serves the on-disk cache when it exists; otherwise fetches the library
    artists once (for the default user) and caches them. A missing-check
    refreshes the cache as a side effect, so it stays in sync with the library.
    """
    settings = get_settings()
    try:
        cached = json.loads(_artist_cache_path(settings).read_text(encoding="utf-8"))
        if cached:
            return {"artists": cached, "cached": True}
    except (OSError, ValueError):
        pass
    try:
        with _jellyfin(settings) as client:
            users = client.get_users()
            user = missing_cli._select_user(users, settings, None)
            if user is None:
                return {"artists": [], "cached": False}
            names = [a.name for a in client.get_artists(user.id)]
    except Exception:  # noqa: BLE001 - a dead server must not 500 the autocomplete
        return {"artists": [], "cached": False}
    _write_artist_cache(settings, names)
    return {"artists": sorted(set(names)), "cached": False}


# --------------------------------------------------------------------------- #
# Missing-songs gap report
# --------------------------------------------------------------------------- #

def run_missing(artist: str | None, user: str | None, all_types: bool, no_cache: bool) -> dict:
    settings = get_settings()
    with _jellyfin(settings) as jellyfin:
        users = jellyfin.get_users()
        selected = missing_cli._select_user(users, settings, user)
        if selected is None:
            raise ConfigError(
                f"Benutzer '{user}' nicht gefunden oder deaktiviert."
                if user
                else "Kein passender Jellyfin-Benutzer gefunden."
            )
        all_artists = jellyfin.get_artists(selected.id)
        _write_artist_cache(settings, [a.name for a in all_artists])
        artists = missing_cli._select_artists(all_artists, settings, artist)
        if not artists:
            raise ConfigError(
                f"Künstler '{artist}' nicht in der Bibliothek von {selected.name}."
                if artist
                else "Keine Künstler zu prüfen."
            )
        cache = (
            None
            if no_cache
            else DiscographyCache(
                settings.state_dir / "discography_cache",
                missing_cli._CACHE_TTL_DAYS * 86400,
            )
        )
        with LastFmProvider(
            api_key=settings.lastfm_api_key,
            timeout_seconds=settings.request_timeout_seconds,
            max_retries=settings.request_max_retries,
            retry_backoff_seconds=settings.retry_backoff_seconds,
            min_request_interval=missing_cli._REQUEST_INTERVAL_SECONDS,
        ) as provider:
            ctx = missing_cli._ScanContext(
                jellyfin=jellyfin,
                provider=provider,
                cache=cache,
                user_id=selected.id,
                include_all_types=all_types,
                console=_QUIET,
            )
            gaps = [missing_cli._gap_for_artist(ctx, art) for art in artists]

    return {
        "user": selected.name,
        "gaps": [_gap_dict(gap) for gap in gaps],
        "total": _grand_total(gaps),
    }


def _album_dict(album: AlbumGap) -> dict:
    return {
        "title": album.title,
        "year": album.year,
        "total_tracks": album.total_tracks,
        "owned_count": album.owned_count,
        "coverage": album.coverage,
        "is_complete": album.is_complete,
        "missing_titles": album.missing_titles,
    }


def _gap_dict(gap: ArtistGap) -> dict:
    coverage = gap.owned_tracks / gap.total_tracks if gap.total_tracks else 1.0
    return {
        "artist_name": gap.artist_name,
        "error": gap.error,
        "album_count": len(gap.albums),
        "complete_album_count": gap.complete_album_count,
        "owned_tracks": gap.owned_tracks,
        "total_tracks": gap.total_tracks,
        "coverage": coverage,
        "albums": [_album_dict(a) for a in gap.albums],
    }


def _grand_total(gaps: list[ArtistGap]) -> dict | None:
    scanned = [g for g in gaps if not g.error and g.albums]
    if len(scanned) < 2:
        return None
    total_tracks = sum(g.total_tracks for g in scanned)
    owned_tracks = sum(g.owned_tracks for g in scanned)
    return {
        "artist_count": len(scanned),
        "album_count": sum(len(g.albums) for g in scanned),
        "complete_album_count": sum(g.complete_album_count for g in scanned),
        "owned_tracks": owned_tracks,
        "total_tracks": total_tracks,
        "coverage": owned_tracks / total_tracks if total_tracks else 1.0,
    }


# --------------------------------------------------------------------------- #
# Purge (delete by prefix)
# --------------------------------------------------------------------------- #

def _effective_prefix(settings: Settings, prefix: str | None) -> str:
    effective = prefix if prefix else settings.playlist_name_prefix
    if not effective:
        raise ConfigError("Prefix ist leer — das würde ALLE Playlists löschen.")
    return effective


def purge_preview(prefix: str | None) -> dict:
    settings = get_settings()
    effective = _effective_prefix(settings, prefix)
    with _jellyfin(settings) as client:
        users = client.get_users()
        found = purge_cli._collect_managed_playlists(client, users, effective, _QUIET)
    return {
        "prefix": effective,
        "user_count": len(users),
        "playlists": [
            {"id": p.id, "name": p.name, "users": p.user_names} for p in found
        ],
    }


def purge_execute(prefix: str | None) -> dict:
    settings = get_settings()
    effective = _effective_prefix(settings, prefix)
    with _jellyfin(settings) as client:
        users = client.get_users()
        found = purge_cli._collect_managed_playlists(client, users, effective, _QUIET)
        if not found:
            return {"prefix": effective, "deleted": 0, "failed": 0}
        deleted, failed = purge_cli._delete_all(client, found, _QUIET)
    return {"prefix": effective, "deleted": deleted, "failed": failed}


# --------------------------------------------------------------------------- #
# Prune (keep allowlist, delete the rest)
# --------------------------------------------------------------------------- #

def _keep_set(keep: list[str]) -> set[str]:
    keep_set = prune_cli._parse_keep(keep)
    if not keep_set:
        raise ConfigError("Keine Keep-Liste — das würde ALLE Playlists löschen.")
    return keep_set


def _classify_prune(playlists, keep_set, rename_prefix):
    """Split playlists by their prefix-stripped base name, computing it once each.

    Returns ``(keepers, to_delete, to_rename)`` where ``keepers`` is a list of
    ``(playlist, base_name)`` pairs and the others are plain playlist lists.
    (Playlists are unhashable, so a list of pairs — not a dict — is the carrier.)
    """
    based = [(p, prune_cli._base_name(p.name, rename_prefix)) for p in playlists]
    keepers = [(p, b) for p, b in based if b in keep_set]
    to_delete = [p for p, b in based if b not in keep_set]
    to_rename = [p for p, b in keepers if p.name != rename_prefix + b]
    return keepers, to_delete, to_rename


def prune_preview(keep: list[str], rename_prefix: str) -> dict:
    settings = get_settings()
    keep_set = _keep_set(keep)
    with _jellyfin(settings) as client:
        users = client.get_users()
        playlists = prune_cli._collect_playlists(client, users, _QUIET)
    keepers, to_delete, to_rename = _classify_prune(playlists, keep_set, rename_prefix)
    matched = {b for _, b in keepers}
    return {
        "user_count": len(users),
        "playlist_count": len(playlists),
        "rename_prefix": rename_prefix,
        "keep": [
            {
                "name": p.name,
                "target": rename_prefix + b,
                "will_rename": p in to_rename,
            }
            for p, b in sorted(keepers, key=lambda kb: kb[0].name.lower())
        ],
        "delete": [
            {"name": p.name, "users": p.user_names}
            for p in sorted(to_delete, key=lambda p: p.name.lower())
        ],
        "unmatched": sorted(keep_set - matched),
    }


def prune_execute(keep: list[str], rename_prefix: str) -> dict:
    settings = get_settings()
    keep_set = _keep_set(keep)
    with _jellyfin(settings) as client:
        users = client.get_users()
        playlists = prune_cli._collect_playlists(client, users, _QUIET)
        keepers, to_delete, to_rename = _classify_prune(playlists, keep_set, rename_prefix)
        renamed, rename_failed = prune_cli._rename_keepers(
            client, users[0].id, to_rename, rename_prefix, _QUIET
        )
        deleted, delete_failed = prune_cli._delete_playlists(client, to_delete, _QUIET)
    return {
        "renamed": renamed,
        "rename_failed": rename_failed,
        "deleted": deleted,
        "delete_failed": delete_failed,
        "kept": len(keepers),
    }
