"""topsongs-live — a concert, or a mix of the last concerts, as a Jellyfin playlist.

Reads the artist's setlists from setlist.fm (SETLISTFM_API_KEY) and builds a
playlist from the songs in your library. One concert keeps its running order; a
mix puts the most played songs first. Each chosen user gets a copy matched
against their own library; --public makes one playlist every user sees. It only
ever creates playlists — an existing name gets a counter, nothing is replaced or
deleted.

    topsongs-live "Metallica" --list
    topsongs-live "Metallica" --last 5 --per-venue
    topsongs-live "Metallica" --tour "M72 World Tour" --min-share 66
    topsongs-live "Metallica" --city Berlin --last 2 --user alice,bob
    topsongs-live "Metallica" --pick 1,3,4 --all-users --dry-run
    topsongs-live "Metallica" --last 3 --public
    topsongs-live --setlist https://www.setlist.fm/setlist/metallica/2026/olympiastadion-berlin-germany-3bd6c4f8.html
"""
from __future__ import annotations

import argparse
import logging
import sys

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import i18n, live
from .config import Settings
from .filters import UserFilter
from .i18n import t
from .jellyfin import JellyfinClient
from .logging_setup import configure_logging
from .missing_cli import _select_user
from .models import Concert, JellyfinUser, LiveMix
from .providers.setlistfm import SetlistFmError, parse_setlist_ref

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="topsongs-live",
        description=t(
            "Creates a Jellyfin playlist from a concert or a mix of the last concerts "
            "(setlist.fm). Never deletes or replaces anything."
        ),
    )
    parser.add_argument(
        "artist", nargs="?", help=t("Artist from the library. May be left out with --setlist.")
    )
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument(
        "--list", action="store_true", help=t("Only list the last 20 concerts, numbered.")
    )
    choice.add_argument(
        "--last",
        type=int,
        metavar="N",
        help=t(
            "Mix of the last N concerts with a setlist (1–{max}). Default: 1.",
            max=live.MAX_CONCERTS,
        ),
    )
    choice.add_argument(
        "--pick",
        metavar="N,N",
        help=t("Concerts by their number from --list, comma-separated (e.g. 1,3,4)."),
    )
    choice.add_argument(
        "--setlist",
        action="append",
        metavar="ID|URL",
        help=t("A specific concert by its setlist.fm id or link. Can be repeated."),
    )
    parser.add_argument("--tour", help=t("Only concerts of this tour (setlist.fm search)."))
    parser.add_argument("--year", type=int, help=t("Only concerts from this year."))
    parser.add_argument("--venue", help=t("Only concerts at this venue."))
    parser.add_argument("--city", help=t("Only concerts in this city."))
    parser.add_argument(
        "--country", help=t("Only concerts in this country (country code, e.g. DE).")
    )
    parser.add_argument(
        "--per-venue",
        action="store_true",
        help=t("With --last: count only the newest night when a venue was played several times."),
    )
    parser.add_argument(
        "--min-share",
        type=int,
        default=50,
        metavar="%",
        help=t(
            "Mix: a song must have been played at this percentage of the concerts or more. "
            "Default: 50."
        ),
    )
    parser.add_argument("--name", help=t("Own playlist name instead of the suggested one."))
    parser.add_argument(
        "--user",
        action="append",
        help=t(
            "Jellyfin user to create the playlist for; repeat or separate with commas for "
            "several. Default: the first active user."
        ),
    )
    parser.add_argument(
        "--all-users", action="store_true", help=t("A copy for every active user.")
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help=t("One playlist every user sees, owned by --user or the first active user."),
    )
    parser.add_argument(
        "--mbid",
        help=t("The artist's MusicBrainz id, when setlist.fm does not know the name uniquely."),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help=t("Only show the preview, create nothing.")
    )
    parser.add_argument("--yes", action="store_true", help=t("Create without asking."))
    return parser


def _parse_picks(value: str) -> list[int]:
    try:
        return [int(part) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise live.LiveError(
            t("--pick expects numbers like 1,3,4, not '{value}'.", value=value)
        ) from exc


def _names(values: list[str] | None) -> list[str]:
    return [name.strip() for value in values or [] for name in value.split(",") if name.strip()]


def main(argv: list[str] | None = None) -> int:
    i18n.use_configured_language()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.artist and not args.setlist:
        parser.error(t("Give an artist or use --setlist."))
    if args.last is not None and not 1 <= args.last <= live.MAX_CONCERTS:
        parser.error(t("--last must be between 1 and {max}.", max=live.MAX_CONCERTS))
    if not 0 <= args.min_share <= 100:
        parser.error(t("--min-share must be between 0 and 100."))
    if args.public and (args.all_users or len(_names(args.user)) > 1):
        parser.error(
            t("--public makes one playlist for everyone: at most one --user, no --all-users.")
        )

    settings = Settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.log_level)
    console = Console()

    try:
        with JellyfinClient(
            base_url=settings.jellyfin_url,
            api_key=settings.jellyfin_api_key,
            timeout_seconds=settings.request_timeout_seconds,
            max_retries=settings.request_max_retries,
            retry_backoff_seconds=settings.retry_backoff_seconds,
        ) as jellyfin, live.setlistfm_client(settings) as setlistfm:
            return _run(args, settings, console, jellyfin, setlistfm)
    except live.ArtistChoiceNeeded as exc:
        console.print(f"[yellow]{escape(str(exc))}[/] {t('Choose one with --mbid:')}")
        for candidate in exc.candidates:
            extra = f"  ({candidate.disambiguation})" if candidate.disambiguation else ""
            console.print(f"  {candidate.mbid}  {escape(candidate.name + extra)}")
        return 1
    except (live.LiveError, SetlistFmError, ValueError) as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        return 1


def _recipients(users: list[JellyfinUser], settings: Settings, args) -> list[JellyfinUser]:
    """Who gets a copy: every active user, the --user names, or the first active user."""
    if args.all_users:
        user_filter = UserFilter(settings.user_allowlist, settings.user_denylist)
        chosen = [user for user in users if user_filter.matches(user)]
    else:
        chosen = []
        for name in _names(args.user) or [None]:
            user = _select_user(users, settings, name)
            if user is None:
                raise live.LiveError(
                    t("User '{name}' not found or disabled.", name=name)
                    if name
                    else t("No matching Jellyfin user found.")
                )
            if user not in chosen:
                chosen.append(user)
    if not chosen:
        raise live.LiveError(t("No matching Jellyfin user found."))
    return chosen


def _run(args, settings: Settings, console: Console, jellyfin, setlistfm) -> int:
    try:
        users = jellyfin.get_users()
    except Exception as exc:  # noqa: BLE001 - clean message, not a traceback
        console.print(f"[red]{t('Jellyfin is not reachable:')}[/] {escape(str(exc))}")
        return 1
    recipients = _recipients(users, settings, args)
    user = recipients[0]

    if args.setlist:
        concerts = [setlistfm.setlist(parse_setlist_ref(ref)) for ref in args.setlist]
        names = {concert.artist_name for concert in concerts}
        if len(names) > 1:
            raise live.LiveError(t("The setlists are by different artists."))
        artist = live.find_library_artist(jellyfin, user, args.artist or names.pop())
    else:
        artist = live.find_library_artist(jellyfin, user, args.artist)
        mbid = live.resolve_mbid(setlistfm, artist, args.mbid)
        concert_filter = live.ConcertFilter(
            tour=args.tour, year=args.year, venue=args.venue, city=args.city, country=args.country
        )
        available = live.load_concerts(setlistfm, mbid, concert_filter)
        if args.list:
            _render_concert_list(console, artist.name, available)
            return 0
        if args.pick:
            concerts = live.pick_concerts(available, _parse_picks(args.pick))
        else:
            concerts = live.select_concerts(available, args.last or 1, args.per_venue)

    share = args.min_share / 100
    tracks = live.local_tracks_for(settings, jellyfin, user, artist)
    mix = live.build_live_mix(artist.name, concerts, tracks, share)
    prefix = settings.live_playlist_prefix
    name = live.playlist_name(
        args.name or live.suggest_name(prefix, artist.name, mix.concerts), prefix
    )
    _render_preview(console, mix, name)
    names = ", ".join(escape(r.name) for r in recipients)
    if args.public:
        console.print(t("Public: one playlist every user sees, owned by {user}.", user=names))
    else:
        console.print(t("For: {users}", users=names))

    if args.dry_run or settings.dry_run:
        console.print(f"\n[yellow]{t('Dry run: nothing created.')}[/]")
        return 0
    if not mix.matched:
        raise live.LiveError(t("None of the songs is in the library; no playlist created."))
    if not args.yes:
        if not sys.stdin.isatty():
            console.print(f"[red]{t('Without a terminal only with --yes.')}[/]")
            return 1
        answer = input("\n" + t("Create the playlist? [y/N] ")).strip().lower()
        if answer not in {"j", "ja", "y", "yes"}:
            console.print(f"[yellow]{t('Cancelled, nothing created.')}[/]")
            return 0

    failed = 0
    for recipient in recipients:
        try:
            if recipient is not user:
                own = live.find_library_artist(jellyfin, recipient, artist.name)
                own_tracks = live.local_tracks_for(settings, jellyfin, recipient, own)
                mix = live.build_live_mix(own.name, concerts, own_tracks, share)
            created = live.create_live_playlist(
                jellyfin, recipient, mix, name, prefix, public=args.public
            )
        except live.LiveError as exc:
            failed += 1
            console.print(f"[red]{escape(recipient.name)}: {escape(str(exc))}[/]")
            continue
        console.print(
            f"[green]{t('Created:')}[/] "
            + t(
                "{name} with {count} songs for {user}.",
                name=escape(created.name),
                count=created.track_count,
                user=escape(recipient.name),
            )
        )
        if created.warning:
            console.print(f"[yellow]{escape(created.warning)}[/]")
    return 1 if failed else 0


def _render_concert_list(console: Console, artist_name: str, concerts: list[Concert]) -> None:
    if not concerts:
        console.print(
            "[yellow]"
            + t("setlist.fm has no matching concerts by {artist}.", artist=escape(artist_name))
            + "[/]"
        )
        return
    table = Table(title=t("{artist} · last concerts (setlist.fm)", artist=escape(artist_name)))
    columns = (t("No."), t("Date"), "Venue", t("Country"), "Tour", "Songs")
    for index, column in enumerate(columns):
        table.add_column(column, justify="right" if index in (0, 5) else "left")
    for number, concert in enumerate(concerts, start=1):
        songs = str(len(concert.songs)) if concert.songs else f"[dim]{t('none yet')}[/]"
        table.add_row(
            str(number),
            i18n.fmt_date(concert.event_date),
            escape(concert.place),
            escape(concert.country_code or ""),
            escape(concert.tour or ""),
            songs,
        )
    console.print(table)


def _render_preview(console: Console, mix: LiveMix, name: str) -> None:
    total = len(mix.concerts)
    count = t("1 concert") if total == 1 else t("{count} concerts", count=total)
    console.print(f"[bold]{escape(mix.artist_name)}[/] · {count}")
    for concert in mix.concerts:
        tour = f"  [dim]({escape(concert.tour)})[/]" if concert.tour else ""
        console.print(f"  {i18n.fmt_date(concert.event_date)}  {escape(concert.place)}{tour}")

    table = Table(show_edge=False)
    table.add_column("#", justify="right")
    table.add_column("Song")
    if total > 1:
        table.add_column(t("played"), justify="right")
    table.add_column(t("Library"))
    for number, song in enumerate(mix.songs, start=1):
        title = escape(song.title) + (f" [dim]· {t('encore')}[/]" if song.encore else "")
        if song.cover_artist:
            cover = t("cover of {artist}", artist=escape(song.cover_artist))
            title += f" [dim]· {cover}[/]"
        status = "[green]✓[/]" if song.jellyfin_item_id else f"[red]{t('✗ missing')}[/]"
        row = [str(number), title]
        if total > 1:
            row.append(f"{song.play_count}/{total}")
        table.add_row(*row, status)
    console.print(table)

    if mix.below_threshold:
        rare = escape(
            ", ".join(f"{s.title} ({s.play_count}/{total})" for s in mix.below_threshold)
        )
        below = t(
            "Played at fewer than {share} % of the concerts: {songs}",
            share=round(mix.min_share * 100),
            songs=rare,
        )
        console.print(f"[dim]{below}[/]")
    console.print(
        "\n"
        + t(
            "{matched} of {total} songs in the library. Name: {name}",
            matched=len(mix.matched),
            total=len(mix.songs),
            name=f"[bold]{escape(name)}[/]",
        )
    )


if __name__ == "__main__":
    sys.exit(main())
