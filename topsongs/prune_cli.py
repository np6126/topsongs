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
from rich.markup import escape

from . import i18n
from .config import Settings
from .i18n import t, tn
from .jellyfin import JellyfinClient
from .live import split_live
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
    tags: list[str] = field(default_factory=list)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="topsongs-prune",
        description=t(
            "Keeps only the playlists named with --keep and deletes all others, across ALL "
            "Jellyfin users. Kept ones can be renamed with --rename-prefix."
        ),
    )
    parser.add_argument(
        "--keep",
        action="append",
        default=[],
        metavar="NAME",
        help=t(
            "Name of a playlist to keep. Repeat or separate with commas "
            "(e.g. --keep Alice --keep Bob or --keep Alice,Bob). Required."
        ),
    )
    parser.add_argument(
        "--rename-prefix",
        default="",
        metavar="PREFIX",
        help=t("Prefix to rename kept playlists with (e.g. '_'). Default: none."),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=t("Only show what would happen, without changing anything."),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=t("Run without asking."),
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
                "[yellow]"
                + t("Could not load the playlists of {user}, skipped:", user=escape(user.name))
                + f"[/] {escape(str(exc))}"
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
                    id=playlist.id,
                    name=playlist.name,
                    user_names=[user.name],
                    tags=playlist.tags,
                )
            else:
                entry.user_names.append(user.name)
    return list(found.values())


def _confirm(console: Console, delete_count: int) -> bool:
    console.print(
        "\n[bold red]"
        + tn(
            "{count} playlist will be deleted irrevocably.",
            "{count} playlists will be deleted irrevocably.",
            delete_count,
        )
        + "[/]"
    )
    try:
        answer = input(t("Type 'yes' to confirm: ")).strip().lower()
    except EOFError:
        return False
    return answer in {"ja", "j", "yes", "y"}


def main(argv: list[str] | None = None) -> int:
    i18n.use_configured_language()
    args = _build_parser().parse_args(argv)
    keep = _parse_keep(args.keep)
    settings = Settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.log_level)
    console = Console()

    if not keep:
        console.print(
            f"[red]{t('No --keep given — that would delete ALL playlists.')} {t('Aborted.')}[/]"
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
        console.print(f"[red]{t('Jellyfin is not reachable:')}[/] {escape(str(exc))}")
        return 1

    # Live playlists were made on request; prune never deletes or renames them.
    live, playlists = split_live(_collect_playlists(jellyfin, users, console))
    keepers = [p for p in playlists if _base_name(p.name, prefix) in keep]
    to_delete = [p for p in playlists if _base_name(p.name, prefix) not in keep]
    to_rename = [p for p in keepers if p.name != prefix + _base_name(p.name, prefix)]

    summary = t(
        "{users}, {playlists} (unique by id).",
        users=tn("{count} user", "{count} users", len(users)),
        playlists=tn("{count} playlist", "{count} playlists", len(playlists) + len(live)),
    )
    console.print(f"[dim]{summary}[/]")
    console.print(f"[bold]{t('KEEP ({count}):', count=len(keepers))}[/]")
    for playlist in sorted(keepers, key=lambda p: p.name.lower()):
        target = prefix + _base_name(playlist.name, prefix)
        if playlist.name == target:
            note = f"  [dim]({t('already fine')})[/]"
        elif prefix:
            note = f"  ->  {escape(target)}"
        else:
            note = ""
        console.print(f"  • {escape(playlist.name)}{note}")
    if live:
        console.print(
            f"[bold]{t('PROTECTED ({count}):', count=len(live))}[/] "
            f"[dim]{t('live playlists, always kept')}[/]"
        )
        for playlist in sorted(live, key=lambda p: p.name.lower()):
            console.print(f"  • {escape(playlist.name)}")
    console.print(f"[bold]{t('DELETE ({count}):', count=len(to_delete))}[/]")
    for playlist in sorted(to_delete, key=lambda p: p.name.lower()):
        console.print(
            f"  • {escape(playlist.name)}  [dim]({escape(', '.join(playlist.user_names))})[/]"
        )

    unmatched = keep - {_base_name(p.name, prefix) for p in keepers} - {p.name for p in live}
    if unmatched:
        names = escape(", ".join(sorted(unmatched)))
        console.print(f"[yellow]{t('Note: no match for --keep: {names}', names=names)}[/]")

    if args.dry_run or settings.dry_run:
        console.print(
            f"\n[yellow]{t('Dry run:')}[/] "
            + t(
                "{delete} would be deleted, {rename} renamed, {keep} kept. Nothing changed.",
                delete=len(to_delete),
                rename=len(to_rename),
                keep=len(keepers),
            )
        )
        return 0

    if not to_delete and not to_rename:
        console.print(f"[green]{t('Nothing to do.')}[/]")
        return 0

    if not args.yes and not _confirm(console, len(to_delete)):
        console.print(f"[yellow]{t('Cancelled. Nothing changed.')}[/]")
        return 0

    # Rename before delete: keepers are never in the delete set, so a rename
    # failure leaves the keeper safely in place under its old name.
    user_id = users[0].id
    renamed, rename_failed = _rename_keepers(jellyfin, user_id, to_rename, prefix, console)
    deleted, delete_failed = _delete_playlists(jellyfin, to_delete, console)

    changed = t("{renamed} renamed, {deleted} deleted", renamed=renamed, deleted=deleted)
    errors = ", ".join(
        [
            tn("{count} rename error", "{count} rename errors", rename_failed),
            tn("{count} delete error", "{count} delete errors", delete_failed),
        ]
    )
    console.print(
        f"\n[green]{changed}[/], [red]{errors}[/], {t('{count} kept.', count=len(keepers))}"
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
                f"[red]{t('Could not rename {name}:', name=escape(playlist.name))}[/] "
                f"{escape(str(exc))}"
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
            console.print(
                f"[red]{t('Could not delete {name}:', name=escape(playlist.name))}[/] "
                f"{escape(str(exc))}"
            )
            logger.exception(
                "event=prune_delete_failed playlist=%s playlist_id=%s error=%s",
                sanitize_untrusted_text(playlist.name),
                playlist.id,
                exc,
            )
    return deleted, failed


if __name__ == "__main__":
    sys.exit(main())
