from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .i18n import t
from .models import AlbumGap, ArtistGap

_BAR_WIDTH = 10
_TITLE_WIDTH = 34


def _coverage_color(coverage: float) -> str:
    if coverage >= 1.0:
        return "green"
    if coverage >= 0.5:
        return "yellow"
    return "red"


def _bar(coverage: float) -> Text:
    filled = max(0, min(_BAR_WIDTH, round(_BAR_WIDTH * coverage)))
    bar = Text()
    bar.append("█" * filled, style=_coverage_color(coverage))
    bar.append("░" * (_BAR_WIDTH - filled), style="grey37")
    return bar


def _truncate(title: str) -> str:
    if len(title) > _TITLE_WIDTH:
        return title[: _TITLE_WIDTH - 1] + "…"
    return title


def _render_album(console: Console, album: AlbumGap) -> None:
    color = _coverage_color(album.coverage)
    line = Text("  ")
    line.append(
        _truncate(album.title).ljust(_TITLE_WIDTH),
        style="bold green" if album.is_complete else "bold",
    )
    if album.year:
        line.append(f"({album.year})  ", style="dim")
    line.append(_bar(album.coverage))
    line.append(f"  {album.owned_count}/{album.total_tracks}", style=color)
    console.print(line)
    for missing in album.missing_titles:
        console.print(Text(f"      ✗ {missing}", style="red"))


def render_artist_gap(console: Console, gap: ArtistGap) -> None:
    if gap.error:
        console.print(
            Text.assemble(("✗ ", "red"), (gap.artist_name, "bold"), (f"  — {gap.error}", "dim"))
        )
        console.print()
        return

    if not gap.albums:
        console.print(
            Text.assemble(
                ("• ", "dim"),
                (gap.artist_name, "bold"),
                (f"  — {t('no albums found on Last.fm')}", "dim"),
            )
        )
        console.print()
        return

    coverage = gap.owned_tracks / gap.total_tracks if gap.total_tracks else 1.0
    pct = round(coverage * 100)
    summary = Text.assemble(
        (f"{gap.complete_album_count}/{len(gap.albums)}", "bold"),
        (f" {t('albums')} · ", "dim"),
        (f"{gap.owned_tracks}/{gap.total_tracks}", "bold"),
        (f" {t('tracks')} · ", "dim"),
        (f"{pct}%", f"bold {_coverage_color(coverage)}"),
    )
    console.print(
        Panel(
            summary,
            title=gap.artist_name,
            title_align="left",
            border_style=_coverage_color(coverage),
            expand=False,
        )
    )
    for album in gap.albums:
        _render_album(console, album)
    console.print()


def render_grand_total(console: Console, gaps: list[ArtistGap]) -> None:
    scanned = [gap for gap in gaps if not gap.error and gap.albums]
    if not scanned:
        return

    total_albums = sum(len(gap.albums) for gap in scanned)
    complete_albums = sum(gap.complete_album_count for gap in scanned)
    total_tracks = sum(gap.total_tracks for gap in scanned)
    owned_tracks = sum(gap.owned_tracks for gap in scanned)
    coverage = owned_tracks / total_tracks if total_tracks else 1.0
    pct = round(coverage * 100)

    summary = Text.assemble(
        (f"{len(scanned)}", "bold"),
        (f" {t('artists')} · ", "dim"),
        (f"{complete_albums}/{total_albums}", "bold"),
        (f" {t('albums complete')} · ", "dim"),
        (f"{owned_tracks}/{total_tracks}", "bold"),
        (f" {t('tracks')} · ", "dim"),
        (f"{pct}%", f"bold {_coverage_color(coverage)}"),
    )
    console.print(
        Panel(
            summary,
            title=t("Total"),
            title_align="left",
            border_style=_coverage_color(coverage),
            expand=False,
        )
    )
