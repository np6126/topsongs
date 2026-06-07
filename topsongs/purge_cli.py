"""topsongs-purge — delete all topsongs-created playlists for every user.

Deletes every playlist whose name starts with the configured PLAYLIST_NAME_PREFIX
(or the prefix given via --prefix), across ALL Jellyfin users. Refuses an empty
prefix (that would match every playlist). Use --dry-run to preview; deletion asks
for confirmation unless --yes. See topsongs-prune for an allowlist-based
"delete everything except these" cleanup.

    topsongs-purge --dry-run
    topsongs-purge --prefix "Top Songs - " --yes
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field

from rich.console import Console

from .config import Settings
from .jellyfin import JellyfinClient
from .logging_setup import configure_logging
from .models import JellyfinUser
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
        description=(
            "Löscht alle von topsongs erstellten Playlists (erkannt am "
            "PLAYLIST_NAME_PREFIX) für ALLE Jellyfin-Benutzer."
        ),
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help=(
            "Namens-Prefix der zu löschenden Playlists. "
            "Standard: PLAYLIST_NAME_PREFIX aus der Konfiguration."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur anzeigen, was gelöscht würde, ohne etwas zu verändern.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Ohne interaktive Rückfrage löschen.",
    )
    return parser


def _collect_managed_playlists(
    jellyfin: JellyfinClient,
    users: list[JellyfinUser],
    prefix: str,
    console: Console,
) -> list[_ManagedPlaylist]:
    found: dict[str, _ManagedPlaylist] = {}
    for user in users:
        try:
            playlists = jellyfin.get_playlists_for_user(user.id)
        except Exception as exc:  # noqa: BLE001 - skip one user, keep purging the rest
            console.print(
                f"[yellow]Playlists für '{user.name}' nicht ladbar, übersprungen:[/] {exc}"
            )
            logger.warning(
                "event=purge_user_skipped user=%s error=%s",
                sanitize_untrusted_text(user.name),
                exc,
            )
            continue
        for playlist in playlists:
            if not playlist.name.startswith(prefix):
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
        f"\n[bold red]{count} Playlists werden unwiderruflich gelöscht.[/]"
    )
    try:
        answer = input("Zum Bestätigen 'ja' eingeben: ").strip().lower()
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
            console.print(f"[red]Fehler beim Löschen von '{playlist.name}':[/] {exc}")
            logger.exception(
                "event=purge_delete_failed playlist=%s playlist_id=%s error=%s",
                sanitize_untrusted_text(playlist.name),
                playlist.id,
                exc,
            )
    return deleted, failed


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = Settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.log_level)
    console = Console()

    prefix = args.prefix if args.prefix is not None else settings.playlist_name_prefix
    if not prefix:
        console.print(
            "[red]Prefix ist leer — ein Purge würde ALLE Playlists löschen. "
            "Abbruch.[/]"
        )
        return 1

    with JellyfinClient(
        base_url=settings.jellyfin_url,
        api_key=settings.jellyfin_api_key,
        timeout_seconds=settings.request_timeout_seconds,
        max_retries=settings.request_max_retries,
        retry_backoff_seconds=settings.retry_backoff_seconds,
    ) as jellyfin:
        return _purge(args, settings, console, jellyfin, prefix)


def _purge(
    args: argparse.Namespace,
    settings: Settings,
    console: Console,
    jellyfin: JellyfinClient,
    prefix: str,
) -> int:
    try:
        users = jellyfin.get_users()
    except Exception as exc:  # noqa: BLE001 - surface a clean message, not a traceback
        console.print(f"[red]Jellyfin nicht erreichbar:[/] {exc}")
        return 1

    playlists = _collect_managed_playlists(jellyfin, users, prefix, console)
    if not playlists:
        console.print(f"[green]Keine Playlists mit Präfix '{prefix}' gefunden.[/]")
        return 0

    console.print(
        f"[dim]Gefunden: {len(playlists)} Playlists mit Präfix '{prefix}' "
        f"über {len(users)} Benutzer.[/]"
    )
    for playlist in playlists:
        console.print(
            f"  • {playlist.name}  [dim]({', '.join(playlist.user_names)})[/]"
        )

    if args.dry_run or settings.dry_run:
        console.print(
            f"\n[yellow]Dry-Run:[/] {len(playlists)} Playlists würden gelöscht. "
            "Nichts wurde verändert."
        )
        return 0

    if not args.yes and not _confirm(console, len(playlists)):
        console.print("[yellow]Abgebrochen. Nichts wurde gelöscht.[/]")
        return 0

    deleted, failed = _delete_all(jellyfin, playlists, console)
    console.print(f"\n[green]{deleted} gelöscht[/], [red]{failed} fehlgeschlagen[/].")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
