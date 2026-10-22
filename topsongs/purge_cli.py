"""topsongs-purge — delete all playlists of the nightly run for every user.

Deletes the playlists the nightly run owns, tagged PLAYLIST_MANAGED_TAG, or
with --prefix every playlist whose name starts with it, across ALL Jellyfin
users. Live playlists are never deleted. Refuses an empty prefix (that would
match every playlist).
Use --dry-run to preview; deletion asks for confirmation unless --yes. See
topsongs-prune for an allowlist-based "delete everything except these" cleanup.

    topsongs-purge --dry-run
    topsongs-purge --prefix "Top Songs - " --yes
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from rich.console import Console
from rich.markup import escape

from . import i18n
from .config import Settings
from .i18n import t
from .jellyfin import JellyfinClient
from .logging_setup import configure_logging
from .models import JellyfinPlaylist, JellyfinUser
from .ownership import is_live, is_nightly
from .sanitize import sanitize_untrusted_text

logger = logging.getLogger(__name__)


@dataclass
class _ManagedPlaylist:
    """A topsongs-created playlist plus every user it was found under.

    Deduplicated by playlist id: a playlist shared with several users surfaces
    once, so it is never deleted twice (the second DELETE would 404)."""

    id: str
    name: str
    user_names: list[str] = field(default_factory=list)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="topsongs-purge",
        description=t(
            "Deletes the nightly run's playlists (recognized by the PLAYLIST_MANAGED_TAG "
            "tag) for ALL Jellyfin users. Never live playlists."
        ),
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help=t("Instead, delete every playlist whose name starts with this (except live ones)."),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=t("Only show what would be deleted, without changing anything."),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=t("Delete without asking."),
    )
    return parser


def _selection(
    settings: Settings, prefix: str | None
) -> tuple[str, Callable[[JellyfinPlaylist], bool]]:
    """What purge deletes, as (description, test): the nightly run's playlists,
    or with a prefix every name that starts with it. Live playlists never."""
    if prefix is None:
        return (
            t("tag '{tag}'", tag=settings.playlist_managed_tag),
            lambda playlist: is_nightly(playlist, settings),
        )
    if not prefix:
        raise ValueError(t("The prefix is empty — a purge would delete ALL playlists."))
    return (
        t("prefix '{prefix}'", prefix=prefix),
        lambda playlist: playlist.name.startswith(prefix) and not is_live(playlist),
    )


def _collect_managed_playlists(
    jellyfin: JellyfinClient,
    users: list[JellyfinUser],
    selects: Callable[[JellyfinPlaylist], bool],
    console: Console,
) -> list[_ManagedPlaylist]:
    found: dict[str, _ManagedPlaylist] = {}
    for user in users:
        try:
            playlists = jellyfin.get_playlists_for_user(user.id)
        except Exception as exc:  # noqa: BLE001 - skip one user, keep purging the rest
            console.print(
                "[yellow]"
                + t("Could not load the playlists of {user}, skipped:", user=escape(user.name))
                + f"[/] {escape(str(exc))}"
            )
            logger.warning(
                "event=purge_user_skipped user=%s error=%s",
                sanitize_untrusted_text(user.name),
                exc,
            )
            continue
        for playlist in playlists:
            if not selects(playlist):
                continue
            entry = found.get(playlist.id)
            if entry is None:
                found[playlist.id] = _ManagedPlaylist(
                    id=playlist.id,
                    name=playlist.name,
                    user_names=[user.name],
                )
            else:
                entry.user_names.append(user.name)
    return list(found.values())


def _confirm(console: Console, count: int) -> bool:
    console.print(
        f"\n[bold red]{t('{count} playlists will be deleted irrevocably.', count=count)}[/]"
    )
    try:
        answer = input(t("Type 'yes' to confirm: ")).strip().lower()
    except EOFError:
        return False
    return answer in {"ja", "j", "yes", "y"}


def _delete_all(
    jellyfin: JellyfinClient,
    playlists: list[_ManagedPlaylist],
    console: Console,
) -> tuple[int, int]:
    deleted = 0
    failed = 0
    for playlist in playlists:
        try:
            jellyfin.delete_playlist(playlist.id)
            deleted += 1
            logger.info(
                "event=purge_deleted playlist=%s playlist_id=%s",
                sanitize_untrusted_text(playlist.name),
                playlist.id,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue with the rest
            failed += 1
            console.print(
                f"[red]{t('Could not delete {name}:', name=escape(playlist.name))}[/] "
                f"{escape(str(exc))}"
            )
            logger.exception(
                "event=purge_delete_failed playlist=%s playlist_id=%s error=%s",
                sanitize_untrusted_text(playlist.name),
                playlist.id,
                exc,
            )
    return deleted, failed


def main(argv: list[str] | None = None) -> int:
    i18n.use_configured_language()
    args = _build_parser().parse_args(argv)
    settings = Settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.log_level)
    console = Console()

    try:
        selection = _selection(settings, args.prefix)
    except ValueError as exc:
        console.print(f"[red]{exc} {t('Aborted.')}[/]")
        return 1

    with JellyfinClient(
        base_url=settings.jellyfin_url,
        api_key=settings.jellyfin_api_key,
        timeout_seconds=settings.request_timeout_seconds,
        max_retries=settings.request_max_retries,
        retry_backoff_seconds=settings.retry_backoff_seconds,
    ) as jellyfin:
        return _purge(args, settings, console, jellyfin, selection)


def _purge(
    args: argparse.Namespace,
    settings: Settings,
    console: Console,
    jellyfin: JellyfinClient,
    selection: tuple[str, Callable[[JellyfinPlaylist], bool]],
) -> int:
    try:
        users = jellyfin.get_users()
    except Exception as exc:  # noqa: BLE001 - surface a clean message, not a traceback
        console.print(f"[red]{t('Jellyfin is not reachable:')}[/] {escape(str(exc))}")
        return 1

    described, selects = selection
    playlists = _collect_managed_playlists(jellyfin, users, selects, console)
    if not playlists:
        console.print(
            f"[green]{t('No playlists with {selection} found.', selection=escape(described))}[/]"
        )
        return 0

    console.print(
        "[dim]"
        + t(
            "Found {count} playlists with {selection} across {users} users.",
            count=len(playlists),
            selection=escape(described),
            users=len(users),
        )
        + "[/]"
    )
    for playlist in playlists:
        console.print(
            f"  • {escape(playlist.name)}  [dim]({escape(', '.join(playlist.user_names))})[/]"
        )

    if args.dry_run or settings.dry_run:
        console.print(
            f"\n[yellow]{t('Dry run:')}[/] "
            + t("{count} playlists would be deleted. Nothing was changed.", count=len(playlists))
        )
        return 0

    if not args.yes and not _confirm(console, len(playlists)):
        console.print(f"[yellow]{t('Cancelled. Nothing was deleted.')}[/]")
        return 0

    deleted, failed = _delete_all(jellyfin, playlists, console)
    console.print(
        f"\n[green]{t('{count} deleted', count=deleted)}[/], "
        f"[red]{t('{count} failed', count=failed)}[/]."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
