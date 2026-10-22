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
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from rich.console import Console

from .. import live, missing_cli, prune_cli, purge_cli
from ..config import Settings
from ..discography import DiscographyCache
from ..filters import UserFilter
from ..i18n import t
from ..jellyfin import JellyfinClient
from ..models import AlbumGap, ArtistGap, Concert, JellyfinUser, MixSong
from ..normalize import normalize_name
from ..ownership import is_live
from ..providers.lastfm import LastFmProvider
from ..providers.setlistfm import SetlistFmClient

# Settings fields that must never be sent to the browser in clear text.
_SECRET_FIELDS = {"jellyfin_api_key", "lastfm_api_key", "setlistfm_api_key"}

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


_ARTIST_CACHE_TTL_SECONDS = 3600


def _artist_cache_path(settings: Settings):
    return settings.state_dir / "artists_cache.json"


def _write_artist_cache(settings: Settings, names: list[str]) -> None:
    """Persist the artist list so the autocompletes are instant."""
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
        "managed_tag": settings.playlist_managed_tag,
        "dry_run_default": settings.dry_run,
        "personalization_weight": settings.personalization_weight,
        "live_enabled": bool(settings.setlistfm_api_key),
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
            display = f"•••• ({t('set')})" if value else f"({t('not set')})"
        elif isinstance(value, list):
            display = ", ".join(value) if value else "—"
        elif isinstance(value, bool):
            display = "true" if value else "false"
        elif value is None:
            display = "—"
        else:
            display = str(value)
        fields.append({"key": alias, "value": display, "secret": secret})
    return {"fields": fields}


# --------------------------------------------------------------------------- #
# Artists (autocomplete)
# --------------------------------------------------------------------------- #

def artist_names() -> dict:
    """Artist names for the Missing and Live autocompletes.

    Served from the on-disk cache while it is younger than an hour; after that
    the default user's library artists are fetched again, so new artists show
    up. When Jellyfin cannot be reached, an older cache still serves.
    """
    settings = get_settings()
    path = _artist_cache_path(settings)
    cached: list[str] = []
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached and time.time() - path.stat().st_mtime < _ARTIST_CACHE_TTL_SECONDS:
            return {"artists": cached, "cached": True}
    except (OSError, ValueError):
        pass
    try:
        with _jellyfin(settings) as client:
            users = client.get_users()
            user = missing_cli._select_user(users, settings, None)
            if user is None:
                return {"artists": cached, "cached": bool(cached)}
            names = [a.name for a in client.get_artists(user.id)]
    except Exception:  # noqa: BLE001 - a dead server must not 500 the autocomplete
        return {"artists": cached, "cached": bool(cached)}
    _write_artist_cache(settings, names)
    return {"artists": sorted(set(names)), "cached": False}


# --------------------------------------------------------------------------- #
# Missing-songs gap report
# --------------------------------------------------------------------------- #

def run_missing(artist: str | None, user: str | None, all_types: bool, no_cache: bool) -> dict:
    settings = get_settings()
    with _jellyfin(settings) as jellyfin:
        selected = _select_user_or_fail(jellyfin, settings, user)
        all_artists = jellyfin.get_artists(selected.id)
        _write_artist_cache(settings, [a.name for a in all_artists])
        artists = missing_cli._select_artists(all_artists, settings, artist)
        if not artists:
            raise ConfigError(
                t("'{artist}' is not in {user}'s library.", artist=artist, user=selected.name)
                if artist
                else t("No artists to check.")
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
# Purge (the nightly run's playlists, or all with a prefix)
# --------------------------------------------------------------------------- #

def _purge_selection(settings: Settings, prefix: str | None):
    try:
        return purge_cli._selection(settings, prefix)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def purge_preview(prefix: str | None) -> dict:
    settings = get_settings()
    described, selects = _purge_selection(settings, prefix)
    with _jellyfin(settings) as client:
        users = client.get_users()
        found = purge_cli._collect_managed_playlists(client, users, selects, _QUIET)
    return {
        "selection": described,
        "user_count": len(users),
        "playlists": [
            {"id": p.id, "name": p.name, "users": p.user_names} for p in found
        ],
    }


def purge_execute(prefix: str | None) -> dict:
    settings = get_settings()
    described, selects = _purge_selection(settings, prefix)
    with _jellyfin(settings) as client:
        users = client.get_users()
        found = purge_cli._collect_managed_playlists(client, users, selects, _QUIET)
        if not found:
            return {"selection": described, "deleted": 0, "failed": 0}
        deleted, failed = purge_cli._delete_all(client, found, _QUIET)
    return {"selection": described, "deleted": deleted, "failed": failed}


# --------------------------------------------------------------------------- #
# Prune (keep allowlist, delete the rest)
# --------------------------------------------------------------------------- #

def _keep_set(keep: list[str]) -> set[str]:
    keep_set = prune_cli._parse_keep(keep)
    if not keep_set:
        raise ConfigError(t("No keep list — that would delete ALL playlists."))
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
        live_found, playlists = live.split_live(prune_cli._collect_playlists(client, users, _QUIET))
    keepers, to_delete, to_rename = _classify_prune(playlists, keep_set, rename_prefix)
    matched = {b for _, b in keepers} | {p.name for p in live_found}
    return {
        "user_count": len(users),
        "playlist_count": len(playlists) + len(live_found),
        "rename_prefix": rename_prefix,
        "protected": [
            {"name": p.name, "users": p.user_names}
            for p in sorted(live_found, key=lambda p: p.name.lower())
        ],
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
        _, playlists = live.split_live(prune_cli._collect_playlists(client, users, _QUIET))
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


# --------------------------------------------------------------------------- #
# Live playlists (setlist.fm)
# --------------------------------------------------------------------------- #

# One client per process, so its 10-minute cache and request spacing hold
# across the list, preview and create calls of the dashboard.
_setlistfm: SetlistFmClient | None = None
_setlistfm_lock = threading.Lock()

# User, artist and their filtered tracks per (user, artist) for 10 minutes, so
# each click in the Live view's preview does not query Jellyfin again.
_LIBRARY_TTL_SECONDS = 600
_library_cache: dict[tuple[str, str], tuple[float, JellyfinUser, live.LibraryArtist, list]] = {}
_library_lock = threading.Lock()


def _setlistfm_client(settings: Settings) -> SetlistFmClient:
    global _setlistfm
    with _setlistfm_lock:
        if _setlistfm is None:
            _setlistfm = live.setlistfm_client(settings)
        return _setlistfm


def _select_user_or_fail(jellyfin: JellyfinClient, settings: Settings, name: str | None):
    selected = missing_cli._select_user(jellyfin.get_users(), settings, name)
    if selected is None:
        raise ConfigError(
            t("User '{name}' not found or disabled.", name=name)
            if name
            else t("No matching Jellyfin user found.")
        )
    return selected


def _library_artist(settings: Settings, user: str | None, artist: str):
    """Return (user, library artist, local tracks), cached for 10 minutes."""
    key = (user or "", normalize_name(artist))
    now = time.monotonic()
    with _library_lock:
        hit = _library_cache.get(key)
        if hit and hit[0] > now:
            return hit[1:]
    with _jellyfin(settings) as jellyfin:
        selected = _select_user_or_fail(jellyfin, settings, user)
        library_artist = live.find_library_artist(jellyfin, selected, artist)
        tracks = live.local_tracks_for(settings, jellyfin, selected, library_artist)
    with _library_lock:
        for stale in [k for k, (expires, *_) in _library_cache.items() if expires <= now]:
            del _library_cache[stale]
        _library_cache[key] = (now + _LIBRARY_TTL_SECONDS, selected, library_artist, tracks)
    return selected, library_artist, tracks


def user_names() -> dict:
    """Users the dashboard may create playlists for; the first is the default."""
    settings = get_settings()
    with _jellyfin(settings) as client:
        users = client.get_users()
    user_filter = UserFilter(settings.user_allowlist, settings.user_denylist)
    names = [user.name for user in users if user_filter.matches(user)]
    return {"users": names, "default": names[0] if names else None}


def _concert_dict(concert: Concert) -> dict:
    return {
        "id": concert.id,
        "url": concert.url,
        "date": concert.event_date.isoformat() if concert.event_date else None,
        "place": concert.place,
        "venue_key": concert.venue_key,
        "country": concert.country_code,
        "tour": concert.tour,
        "song_count": len(concert.songs),
    }


def live_concerts(
    artist: str,
    user: str | None,
    mbid: str | None = None,
    concert_filter: live.ConcertFilter | None = None,
) -> dict:
    settings = get_settings()
    setlistfm = _setlistfm_client(settings)
    selected, library_artist, _ = _library_artist(settings, user, artist)
    try:
        resolved = live.resolve_mbid(setlistfm, library_artist, mbid)
    except live.ArtistChoiceNeeded as exc:
        return {
            "artist": library_artist.name,
            "needs_choice": True,
            "candidates": [c.model_dump() for c in exc.candidates],
        }
    concerts = live.load_concerts(setlistfm, resolved, concert_filter)
    # Suggestions also draw on the unfiltered list, so filtering never shrinks
    # them. Without a filter it is the same request, answered from the cache.
    unfiltered = live.load_concerts(setlistfm, resolved)
    return {
        "artist": library_artist.name,
        "user": selected.name,
        "concerts": [_concert_dict(c) for c in concerts],
        "suggestions": live.suggestions(unfiltered + concerts),
    }


def _live_mix(settings: Settings, artist: str, user: str | None, setlist_ids, min_share):
    ids = list(dict.fromkeys(setlist_ids))
    if len(ids) > live.MAX_CONCERTS:
        raise live.LiveError(t("At most {max} concerts per mix.", max=live.MAX_CONCERTS))
    setlistfm = _setlistfm_client(settings)
    concerts = [setlistfm.setlist(setlist_id) for setlist_id in ids]
    selected, library_artist, tracks = _library_artist(settings, user, artist)
    share = min(1.0, max(0.0, min_share))
    return selected, live.build_live_mix(library_artist.name, concerts, tracks, share)


def _mix_song_dict(song: MixSong) -> dict:
    return {
        "title": song.title,
        "play_count": song.play_count,
        "encore": song.encore,
        "cover_artist": song.cover_artist,
        "in_library": song.jellyfin_item_id is not None,
    }


def live_preview(artist: str, user: str | None, setlist_ids: list[str], min_share: float) -> dict:
    settings = get_settings()
    selected, mix = _live_mix(settings, artist, user, setlist_ids, min_share)
    return {
        "artist": mix.artist_name,
        "user": selected.name,
        "concert_count": len(mix.concerts),
        "songs": [_mix_song_dict(s) for s in mix.songs],
        "below": [_mix_song_dict(s) for s in mix.below_threshold],
        "matched_count": len(mix.matched),
        "suggested_name": live.suggest_name(
            settings.live_playlist_prefix,
            mix.artist_name,
            mix.concerts,
        ),
    }


def live_create(
    artist: str,
    users: list[str],
    setlist_ids: list[str],
    min_share: float,
    name: str,
    public: bool = False,
) -> dict:
    """A copy for each of users, matched against that user's library; or, when
    public, one playlist owned by the first user that every user sees."""
    settings = get_settings()
    owners: list[str | None] = list(dict.fromkeys(users)) or [None]
    if public:
        owners = owners[:1]
    created, failed = [], []
    for owner in owners:
        try:
            selected, mix = _live_mix(settings, artist, owner, setlist_ids, min_share)
            with _jellyfin(settings) as jellyfin:
                playlist = live.create_live_playlist(
                    jellyfin, selected, mix, name, settings.live_playlist_prefix, public=public
                )
        except (live.LiveError, ConfigError) as exc:
            failed.append({"user": owner, "error": str(exc)})
            continue
        created.append(
            {
                "user": selected.name,
                "name": playlist.name,
                "playlist_id": playlist.playlist_id,
                "track_count": playlist.track_count,
                "warning": playlist.warning,
            }
        )
    if not created:
        raise live.LiveError(failed[0]["error"])
    return {"public": public, "created": created, "failed": failed}


def live_playlists() -> dict:
    """Existing live playlists across all users, for the overview in the Live view."""
    settings = get_settings()
    with _jellyfin(settings) as client:
        users = client.get_users()
        found = purge_cli._collect_managed_playlists(client, users, is_live, _QUIET)
    return {
        "playlists": [
            {"name": p.name, "users": p.user_names}
            for p in sorted(found, key=lambda p: p.name.lower())
        ]
    }
