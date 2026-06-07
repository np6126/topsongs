"""topsongs-prune — keep a named allowlist of playlists, delete all the rest.

Across ALL Jellyfin users this deletes every playlist whose name is not in
``--keep``, and optionally renames the kept ones with ``--rename-prefix``. It is
the surgical counterpart to ``topsongs-purge`` (which deletes by name prefix):
prune is "delete everything except these few".

Usage:
    topsongs-prune --keep Alice --keep Bob --dry-run
    topsongs-prune --keep Alice,Bob --rename-prefix _ --yes

``--keep`` is required (an empty allowlist would wipe every playlist). The kept
names are matched ignoring a leading ``--rename-prefix``, so re-runs are
idempotent: an already-renamed "_Alice" still matches ``--keep Alice`` and is not
deleted. Renames run before deletes; a rename failure never endangers a keeper
because keepers are excluded from the delete set regardless.

Dry-run (``--dry-run`` or DRY_RUN=1) only prints the plan. Otherwise it asks for
confirmation unless ``--yes`` is given.
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
class _Playlist:
    """A playlist plus every user it was found under (deduped by id)."""

    id: str
    name: str
    user_names: list[str] = field(default_factory=list)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="topsongs-prune",
        description=(
            "Behält nur die mit --keep genannten Playlists und löscht alle "
            "anderen — über ALLE Jellyfin-Benutzer. Behaltene können mit "
            "--rename-prefix umbenannt werden."
        ),
    )
    parser.add_argument(
        "--keep",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Name einer zu behaltenden Playlist. Mehrfach oder kommagetrennt "
            "(z.B. --keep Alice --keep Bob oder --keep Alice,Bob). Pflicht."
        ),
    )
    parser.add_argument(
        "--rename-prefix",
        default="",
        metavar="PREFIX",
        help="Prefix, mit dem behaltene Playlists umbenannt werden (z.B. '_'). Standard: keiner.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur anzeigen, was passieren würde, ohne etwas zu verändern.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Ohne interaktive Rückfrage ausführen.",
    )
    return parser


def _parse_keep(values: list[str]) -> set[str]:
    names: set[str] = set()
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                names.add(part)
    return names


def _base_name(name: str, prefix: str) -> str:
    """Strip a leading rename prefix so keep-matching is idempotent."""
    if prefix and name.startswith(prefix):
        return name[len(prefix):]
    return name


def _collect_playlists(
    jellyfin: JellyfinClient,
    users: list[JellyfinUser],
    console: Console,
) -> list[_Playlist]:
    found: dict[str, _Playlist] = {}
    for user in users:
        try:
            # media_types=None: prune covers playlists of every media type.
            playlists = jellyfin.get_playlists_for_user(user.id, media_types=None)
        except Exception as exc:  # noqa: BLE001 - skip one user, keep going
            console.print(
                f"[yellow]Playlists für '{user.name}' nicht ladbar, übersprungen:[/] {exc}"
            )
            logger.warning(
                "event=prune_user_skipped user=%s error=%s",
                sanitize_untrusted_text(user.name),
                exc,
            )
            continue
        for playlist in playlists:
            entry = found.get(playlist.id)
            if entry is None:
                found[playlist.id] = _Playlist(
                    id=playlist.id, name=playlist.name, user_names=[user.name]
                )
            else:
                entry.user_names.append(user.name)
    return list(found.values())


def _confirm(console: Console, delete_count: int) -> bool:
    console.print(
        f"\n[bold red]{delete_count} Playlists werden unwiderruflich gelöscht.[/]"
    )
    try:
        answer = input("Zum Bestätigen 'ja' eingeben: ").strip().lower()
    except EOFError:
        return False
    return answer in {"ja", "j", "yes", "y"}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    keep = _parse_keep(args.keep)
    settings = Settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.log_level)
    console = Console()

    if not keep:
        console.print(
            "[red]Kein --keep angegeben — das würde ALLE Playlists löschen. Abbruch.[/]"
        )
        return 1

    with JellyfinClient(
        base_url=settings.jellyfin_url,
        api_key=settings.jellyfin_api_key,
        timeout_seconds=settings.request_timeout_seconds,
        max_retries=settings.request_max_retries,
        retry_backoff_seconds=settings.retry_backoff_seconds,
    ) as jellyfin:
        return _prune(args, keep, settings, console, jellyfin)


def _prune(
    args: argparse.Namespace,
    keep: set[str],
    settings: Settings,
    console: Console,
    jellyfin: JellyfinClient,
) -> int:
    prefix = args.rename_prefix
    try:
        users = jellyfin.get_users()
    except Exception as exc:  # noqa: BLE001 - clean message, not a traceback
        console.print(f"[red]Jellyfin nicht erreichbar:[/] {exc}")
        return 1

    playlists = _collect_playlists(jellyfin, users, console)
    keepers = [p for p in playlists if _base_name(p.name, prefix) in keep]
    to_delete = [p for p in playlists if _base_name(p.name, prefix) not in keep]
    to_rename = [p for p in keepers if p.name != prefix + _base_name(p.name, prefix)]

    console.print(
        f"[dim]{len(users)} Benutzer, {len(playlists)} Playlists (eindeutig nach id).[/]"
    )
    console.print(f"[bold]BEHALTEN ({len(keepers)}):[/]")
    for playlist in sorted(keepers, key=lambda p: p.name.lower()):
        target = prefix + _base_name(playlist.name, prefix)
        if playlist.name == target:
            note = "  [dim](schon ok)[/]"
        elif prefix:
            note = f"  ->  {target}"
        else:
            note = ""
        console.print(f"  • {playlist.name}{note}")
    console.print(f"[bold]LÖSCHEN ({len(to_delete)}):[/]")
    for playlist in sorted(to_delete, key=lambda p: p.name.lower()):
        console.print(f"  • {playlist.name}  [dim]({', '.join(playlist.user_names)})[/]")

    unmatched = keep - {_base_name(p.name, prefix) for p in keepers}
    if unmatched:
        console.print(
            f"[yellow]Hinweis: kein Treffer für --keep: {', '.join(sorted(unmatched))}[/]"
        )

    if args.dry_run or settings.dry_run:
        console.print(
            f"\n[yellow]Dry-Run:[/] {len(to_delete)} würden gelöscht, "
            f"{len(to_rename)} umbenannt, {len(keepers)} behalten. Nichts verändert."
        )
        return 0

    if not to_delete and not to_rename:
        console.print("[green]Nichts zu tun.[/]")
        return 0

    if not args.yes and not _confirm(console, len(to_delete)):
        console.print("[yellow]Abgebrochen. Nichts verändert.[/]")
        return 0

    # Rename before delete: keepers are never in the delete set, so a rename
    # failure leaves the keeper safely in place under its old name.
    user_id = users[0].id
    renamed, rename_failed = _rename_keepers(jellyfin, user_id, to_rename, prefix, console)
    deleted, delete_failed = _delete_playlists(jellyfin, to_delete, console)

    console.print(
        f"\n[green]{renamed} umbenannt, {deleted} gelöscht[/], "
        f"[red]{rename_failed} rename-Fehler, {delete_failed} delete-Fehler[/], "
        f"{len(keepers)} behalten."
    )
    return 1 if (rename_failed or delete_failed) else 0


def _rename_keepers(
    jellyfin: JellyfinClient,
    user_id: str,
    to_rename: list[_Playlist],
    prefix: str,
    console: Console,
) -> tuple[int, int]:
    renamed = failed = 0
    for playlist in to_rename:
        target = prefix + _base_name(playlist.name, prefix)
        try:
            jellyfin.rename_playlist(user_id, playlist.id, target)
            renamed += 1
            logger.info(
                "event=prune_renamed old=%s new=%s playlist_id=%s",
                sanitize_untrusted_text(playlist.name),
                sanitize_untrusted_text(target),
                playlist.id,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue
            failed += 1
            console.print(
                f"[red]Umbenennen fehlgeschlagen für '{playlist.name}':[/] {exc}"
            )
            logger.exception(
                "event=prune_rename_failed playlist=%s playlist_id=%s error=%s",
                sanitize_untrusted_text(playlist.name),
                playlist.id,
                exc,
            )
    return renamed, failed


def _delete_playlists(
    jellyfin: JellyfinClient,
    to_delete: list[_Playlist],
    console: Console,
) -> tuple[int, int]:
    deleted = failed = 0
    for playlist in to_delete:
        try:
            jellyfin.delete_playlist(playlist.id)
            deleted += 1
            logger.info(
                "event=prune_deleted playlist=%s playlist_id=%s",
                sanitize_untrusted_text(playlist.name),
                playlist.id,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue
            failed += 1
            console.print(f"[red]Löschen fehlgeschlagen für '{playlist.name}':[/] {exc}")
            logger.exception(
                "event=prune_delete_failed playlist=%s playlist_id=%s error=%s",
                sanitize_untrusted_text(playlist.name),
                playlist.id,
                exc,
            )
    return deleted, failed


if __name__ == "__main__":
    sys.exit(main())
