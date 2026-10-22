"""topsongs-missing — show which of an artist's songs are missing from Jellyfin.

Compares each artist's local Jellyfin tracks against their Last.fm discography
and prints the gap. With no artist argument it checks every artist in the
library; results use a 30-day discography cache in the state dir.

    topsongs-missing "Metallica"
    topsongs-missing --user Alice --all-types --no-cache
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

from rich.console import Console
from rich.markup import escape

from . import i18n
from .config import Settings
from .discography import DiscographyCache, compute_artist_gap
from .filters import NameFilter, UserFilter
from .i18n import t
from .jellyfin import JellyfinClient
from .logging_setup import configure_logging
from .missing_report import render_artist_gap, render_grand_total
from .models import ArtistGap, JellyfinArtist, JellyfinUser
from .normalize import normalize_name
from .providers.lastfm import LastFmError, LastFmProvider

logger = logging.getLogger(__name__)

_CACHE_TTL_DAYS = 30
# Last.fm publishes no hard rate limit; ~5 requests/second is the safe norm.
_REQUEST_INTERVAL_SECONDS = 0.2


@dataclass(frozen=True)
class _ScanContext:
    """Run-constant collaborators shared across every artist in one scan."""

    jellyfin: JellyfinClient
    provider: LastFmProvider
    cache: DiscographyCache | None
    user_id: str
    include_all_types: bool
    console: Console


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="topsongs-missing",
        description=t("Shows which songs of an artist are missing from the Jellyfin library."),
    )
    parser.add_argument(
        "artist",
        nargs="?",
        help=t("Artist name. Without one, every artist in the library is checked."),
    )
    parser.add_argument(
        "--user",
        help=t("Jellyfin user whose library is checked. Default: the first active one."),
    )
    parser.add_argument(
        "--all-types",
        action="store_true",
        help=t("Include compilations and live albums too (left out otherwise)."),
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help=t("Ignore the discography cache and load fresh from Last.fm."),
    )
    return parser


def _select_user(
    users: list[JellyfinUser], settings: Settings, requested_name: str | None
) -> JellyfinUser | None:
    if requested_name:
        wanted = normalize_name(requested_name)
        for user in users:
            if normalize_name(user.name) == wanted and not user.policy.is_disabled:
                return user
        return None

    user_filter = UserFilter(settings.user_allowlist, settings.user_denylist)
    for user in users:
        if user_filter.matches(user):
            return user
    return None


def _select_artists(
    all_artists: list[JellyfinArtist], settings: Settings, requested_name: str | None
) -> list[JellyfinArtist]:
    if requested_name:
        wanted = normalize_name(requested_name)
        return [artist for artist in all_artists if normalize_name(artist.name) == wanted]

    name_filter = NameFilter(settings.artist_allowlist, settings.artist_denylist)
    return [artist for artist in all_artists if name_filter.matches(artist.name)]


def _gap_for_artist(ctx: _ScanContext, artist: JellyfinArtist) -> ArtistGap:
    try:
        local_tracks = ctx.jellyfin.get_tracks_for_artist(ctx.user_id, artist)
    except Exception as exc:  # noqa: BLE001 - report any Jellyfin failure per artist
        return ArtistGap(artist_name=artist.name, error=t("Jellyfin error: {error}", error=exc))

    scope = "all" if ctx.include_all_types else "studio"
    discography = ctx.cache.get(artist.name, scope) if ctx.cache is not None else None
    if discography is None:
        try:
            loading = t("Loading discography: {artist}…", artist=escape(artist.name))
            with ctx.console.status(f"[dim]{loading}[/]"):
                discography = ctx.provider.get_discography(
                    artist.name, include_all_types=ctx.include_all_types
                )
        except LastFmError as exc:
            return ArtistGap(artist_name=artist.name, error=t("Last.fm error: {error}", error=exc))
        if ctx.cache is not None:
            ctx.cache.put(artist.name, scope, discography)

    return compute_artist_gap(artist.name, local_tracks, discography)


def main(argv: list[str] | None = None) -> int:
    i18n.use_configured_language()
    args = _build_parser().parse_args(argv)
    settings = Settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.log_level)
    console = Console()

    with JellyfinClient(
        base_url=settings.jellyfin_url,
        api_key=settings.jellyfin_api_key,
        timeout_seconds=settings.request_timeout_seconds,
        max_retries=settings.request_max_retries,
        retry_backoff_seconds=settings.retry_backoff_seconds,
    ) as jellyfin:
        with LastFmProvider(
            api_key=settings.lastfm_api_key,
            timeout_seconds=settings.request_timeout_seconds,
            max_retries=settings.request_max_retries,
            retry_backoff_seconds=settings.retry_backoff_seconds,
            min_request_interval=_REQUEST_INTERVAL_SECONDS,
        ) as provider:
            return _scan(args, settings, console, jellyfin, provider)


def _scan(
    args: argparse.Namespace,
    settings: Settings,
    console: Console,
    jellyfin: JellyfinClient,
    provider: LastFmProvider,
) -> int:
    try:
        users = jellyfin.get_users()
    except Exception as exc:  # noqa: BLE001 - surface a clean message, not a traceback
        console.print(f"[red]{t('Jellyfin is not reachable:')}[/] {escape(str(exc))}")
        return 1

    user = _select_user(users, settings, args.user)
    if user is None:
        if args.user:
            message = t("User '{name}' not found or disabled.", name=escape(args.user))
            console.print(f"[red]{message}[/]")
        else:
            console.print(f"[red]{t('No matching Jellyfin user found.')}[/]")
        return 1

    try:
        all_artists = jellyfin.get_artists(user.id)
    except Exception as exc:  # noqa: BLE001 - surface a clean message, not a traceback
        console.print(f"[red]{t('Could not load the artists:')}[/] {escape(str(exc))}")
        return 1

    artists = _select_artists(all_artists, settings, args.artist)
    if not artists:
        if args.artist:
            message = t(
                "'{artist}' is not in {user}'s library.",
                artist=escape(args.artist),
                user=escape(user.name),
            )
            console.print(f"[red]{message}[/]")
        else:
            console.print(f"[yellow]{t('No artists to check.')}[/]")
        return 1

    cache = (
        None
        if args.no_cache
        else DiscographyCache(
            settings.state_dir / "discography_cache", _CACHE_TTL_DAYS * 86400
        )
    )

    checking = t(
        "Checking {count} artists for user {user} (source: Last.fm)…",
        count=len(artists),
        user=escape(user.name),
    )
    console.print(f"[dim]{checking}[/]\n")

    ctx = _ScanContext(
        jellyfin=jellyfin,
        provider=provider,
        cache=cache,
        user_id=user.id,
        include_all_types=args.all_types,
        console=console,
    )

    gaps: list[ArtistGap] = []
    for artist in artists:
        gap = _gap_for_artist(ctx, artist)
        gaps.append(gap)
        render_artist_gap(console, gap)

    if len(gaps) > 1:
        render_grand_total(console, gaps)

    return 1 if all(gap.error for gap in gaps) else 0


if __name__ == "__main__":
    sys.exit(main())
