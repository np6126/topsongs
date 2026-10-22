"""Live playlists: one concert, or a mix of several, from setlist.fm as a Jellyfin playlist.

Built on request only, by ``topsongs-live`` and the dashboard's Live view. Each
carries the live tag, so the nightly run, purge and prune leave it alone.
Nothing here deletes or replaces a playlist: a name that already exists gets a
counter instead.

A single concert keeps its running order. A mix counts at how many of the chosen
concerts each song was played, keeps the songs played at ``min_share`` of them
or more, and puts the most played first; songs played equally often follow
their typical place in the show.
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .config import Settings
from .filters import LibraryPathFilter
from .i18n import fmt_date, t
from .jellyfin import JellyfinClient
from .matcher import match_tracks
from .models import (
    Concert,
    ConcertFilter,
    JellyfinArtist,
    JellyfinTrack,
    JellyfinUser,
    LiveMix,
    MixSong,
    ProviderTrack,
    SetlistArtist,
)
from .normalize import normalize_name
from .ownership import LIVE_TAG, is_live
from .providers.setlistfm import SetlistFmClient
from .sanitize import sanitize_for_filename, sanitize_untrusted_text

logger = logging.getLogger(__name__)

MAX_CONCERTS = 20


class LiveError(RuntimeError):
    """A problem the user can fix; the message is shown as is."""


class ArtistChoiceNeeded(LiveError):
    """No MusicBrainz id in the tags and the name search is not unambiguous."""

    def __init__(self, artist_name: str, candidates: list[SetlistArtist]) -> None:
        super().__init__(
            t(
                "'{artist}' is ambiguous at setlist.fm. Please choose the right artist.",
                artist=artist_name,
            )
        )
        self.candidates = candidates


@dataclass
class LibraryArtist:
    name: str
    # Every Jellyfin artist with this name; Jellyfin can split a band into
    # spelling variants that each hold part of the tracks.
    artists: list[JellyfinArtist] = field(default_factory=list)

    @property
    def mbid(self) -> str | None:
        return next((artist.mbid for artist in self.artists if artist.mbid), None)


def setlistfm_client(settings: Settings) -> SetlistFmClient:
    if not settings.setlistfm_api_key:
        raise LiveError(t("SETLISTFM_API_KEY is not set; live playlists are off."))
    return SetlistFmClient(
        api_key=settings.setlistfm_api_key,
        timeout_seconds=settings.request_timeout_seconds,
        max_retries=settings.request_max_retries,
        retry_backoff_seconds=settings.retry_backoff_seconds,
    )


# --------------------------------------------------------------------------- #
# Artist and concerts
# --------------------------------------------------------------------------- #

def find_library_artist(
    jellyfin: JellyfinClient, user: JellyfinUser, name: str
) -> LibraryArtist:
    wanted = normalize_name(name)
    artists = [a for a in jellyfin.get_artists(user.id) if normalize_name(a.name) == wanted]
    if not artists:
        raise LiveError(t("'{artist}' is not in {user}'s library.", artist=name, user=user.name))
    return LibraryArtist(name=artists[0].name, artists=artists)


def resolve_mbid(
    setlistfm: SetlistFmClient, artist: LibraryArtist, override: str | None = None
) -> str:
    """The artist's MusicBrainz id: given, from the tags, or an unambiguous name search."""
    if override:
        return override
    if artist.mbid:
        return artist.mbid
    candidates = setlistfm.search_artists(artist.name)
    wanted = normalize_name(artist.name)
    exact = [c for c in candidates if normalize_name(c.name) == wanted]
    if len(exact) == 1:
        return exact[0].mbid
    if not candidates:
        raise LiveError(t("setlist.fm knows no artist '{artist}'.", artist=artist.name))
    raise ArtistChoiceNeeded(artist.name, (exact or candidates)[:10])


def load_concerts(
    setlistfm: SetlistFmClient, mbid: str, concert_filter: ConcertFilter | None = None
) -> list[Concert]:
    """Up to 20 concerts, newest first; with filters via setlist.fm's search."""
    if concert_filter and concert_filter.is_set():
        concerts = setlistfm.search_setlists(mbid, concert_filter)
    else:
        concerts = setlistfm.artist_setlists(mbid)
    return sorted(concerts, key=lambda c: c.event_date or date.min, reverse=True)[:MAX_CONCERTS]


def suggestions(concerts: list[Concert]) -> dict[str, list[str]]:
    """Distinct values per ConcertFilter field, for the filter autocompletes."""
    def distinct(values) -> list[str]:
        return sorted({value for value in values if value}, key=str.casefold)

    return {
        "tour": distinct(c.tour for c in concerts),
        "year": sorted({str(c.event_date.year) for c in concerts if c.event_date}, reverse=True),
        "venue": distinct(c.venue_name for c in concerts),
        "city": distinct(c.city for c in concerts),
        "country": distinct(c.country_code for c in concerts),
    }


def select_concerts(concerts: list[Concert], last: int, per_venue: bool = False) -> list[Concert]:
    """The newest concerts with songs; with per_venue, the newest night per venue only."""
    playable = [concert for concert in concerts if concert.songs]
    if per_venue:
        seen: set[str] = set()
        unique = []
        for concert in playable:
            if concert.venue_key not in seen:
                seen.add(concert.venue_key)
                unique.append(concert)
        playable = unique
    return playable[:last]


def pick_concerts(concerts: list[Concert], numbers: list[int]) -> list[Concert]:
    """Concerts by their 1-based number in the listed order."""
    picked = []
    for number in numbers:
        if not 1 <= number <= len(concerts):
            raise LiveError(
                t(
                    "There is no concert no. {number} (1–{count}).",
                    number=number,
                    count=len(concerts),
                )
            )
        concert = concerts[number - 1]
        if not concert.songs:
            raise LiveError(t("Concert no. {number} has no setlist yet.", number=number))
        if concert not in picked:
            picked.append(concert)
    return picked


# --------------------------------------------------------------------------- #
# Mix
# --------------------------------------------------------------------------- #

@dataclass
class _SongStats:
    titles: Counter = field(default_factory=Counter)
    positions: list[float] = field(default_factory=list)
    encores: int = 0
    cover_artist: str | None = None


def build_mix(concerts: list[Concert], min_share: float) -> tuple[list[MixSong], list[MixSong]]:
    """Return (songs, below_threshold), each most played first.

    A song counts once per concert, so a reprise does not double it. Its position
    is where it came in the show (0 = opener, 1 = closer); the median over the
    concerts orders songs played equally often, which for a single concert is
    exactly its running order.
    """
    stats: dict[str, _SongStats] = {}
    for concert in concerts:
        seen: set[str] = set()
        last_index = max(len(concert.songs) - 1, 1)
        for index, song in enumerate(concert.songs):
            key = normalize_name(song.title) or song.title.casefold()
            if key in seen:
                continue
            seen.add(key)
            entry = stats.setdefault(key, _SongStats())
            entry.titles[song.title] += 1
            entry.positions.append(index / last_index)
            entry.encores += song.encore
            entry.cover_artist = entry.cover_artist or song.cover_artist

    ordered = sorted(
        stats.values(),
        key=lambda e: (
            -len(e.positions),
            statistics.median(e.positions),
            e.titles.most_common(1)[0][0].casefold(),
        ),
    )
    # The small epsilon keeps e.g. 2 of 3 concerts at a 66 % threshold.
    cutoff = (min_share - 1e-3) * len(concerts)
    included: list[MixSong] = []
    below: list[MixSong] = []
    for entry in ordered:
        song = MixSong(
            title=entry.titles.most_common(1)[0][0],
            play_count=len(entry.positions),
            encore=entry.encores * 2 > len(entry.positions),
            cover_artist=entry.cover_artist,
        )
        (included if song.play_count >= cutoff else below).append(song)
    return included, below


def match_library(songs: list[MixSong], local_tracks: list[JellyfinTrack]) -> None:
    """Set each song's Jellyfin track, with the same matching as the nightly run."""
    provider_tracks = [
        ProviderTrack(title=song.title, rank=rank) for rank, song in enumerate(songs, start=1)
    ]
    matches, _ = match_tracks(provider_tracks, local_tracks)
    by_title = {match.provider_title: match for match in matches}
    for song in songs:
        match = by_title.get(song.title)
        song.jellyfin_item_id = match.jellyfin_item_id if match else None


def local_tracks_for(
    settings: Settings, jellyfin: JellyfinClient, user: JellyfinUser, artist: LibraryArtist
) -> list[JellyfinTrack]:
    """The artist's tracks under the library-path filters.

    Unlike the nightly run, short tracks stay: the setlist already says which
    songs belong in, and a 50-second punk song is still a song.
    """
    tracks: dict[str, JellyfinTrack] = {}
    for jellyfin_artist in artist.artists:
        for track in jellyfin.get_tracks_for_artist(user.id, jellyfin_artist):
            tracks.setdefault(track.id, track)
    path_filter = LibraryPathFilter(
        settings.library_path_allowlist, settings.library_path_denylist
    )
    return path_filter.filter_tracks(tracks.values())


def build_live_mix(
    artist_name: str,
    concerts: list[Concert],
    local_tracks: list[JellyfinTrack],
    min_share: float,
) -> LiveMix:
    concerts = list({concert.id: concert for concert in concerts}.values())
    if not concerts:
        raise LiveError(t("No concerts selected."))
    if len(concerts) > MAX_CONCERTS:
        raise LiveError(t("At most {max} concerts per mix.", max=MAX_CONCERTS))
    empty = [concert for concert in concerts if not concert.songs]
    if empty:
        raise LiveError(
            t("No setlist yet: {concerts}", concerts=", ".join(c.place or c.id for c in empty))
        )
    songs, below = build_mix(concerts, min_share)
    match_library(songs + below, local_tracks)
    return LiveMix(
        artist_name=artist_name,
        concerts=concerts,
        songs=songs,
        below_threshold=below,
        min_share=min_share,
    )


# --------------------------------------------------------------------------- #
# Playlist
# --------------------------------------------------------------------------- #

def suggest_name(prefix: str, artist_name: str, concerts: list[Concert]) -> str:
    dates = sorted(c.event_date for c in concerts if c.event_date)
    if len(concerts) == 1:
        when = f" ({dates[0].isoformat()})" if dates else ""
        label = f"{concerts[0].place}{when}" or t("Concert")
    else:
        tours = {c.tour for c in concerts}
        tour = next(iter(tours)) if len(tours) == 1 else None
        span = ""
        if dates:
            span = dates[0].isoformat()
            if dates[-1] != dates[0]:
                span += f" – {dates[-1].isoformat()}"
            span = f" ({span})"
        mix = t("Mix of {count} concerts", count=len(concerts))
        label = f"{tour + ' - ' if tour else ''}{mix}{span}"
    return sanitize_for_filename(sanitize_untrusted_text(f"{prefix}{artist_name} - {label}"))


def unique_name(name: str, existing: set[str]) -> str:
    if name not in existing:
        return name
    counter = 2
    while f"{name} ({counter})" in existing:
        counter += 1
    return f"{name} ({counter})"


def overview_text(mix: LiveMix) -> str:
    lines = [t("Setlists from setlist.fm:")]
    for concert in mix.concerts:
        when = fmt_date(concert.event_date)
        lines.append(f"{when} {concert.place}: {concert.url or 'https://www.setlist.fm'}")
    if len(mix.concerts) > 1:
        lines.append(
            t(
                "Songs played at {share} % of the concerts or more, most played first.",
                share=round(mix.min_share * 100),
            )
        )
    return "\n".join(lines)


@dataclass
class CreatedPlaylist:
    playlist_id: str
    name: str
    track_count: int
    # Set when the playlist exists but its setlist.fm attribution could not be written.
    warning: str | None = None


def split_live(playlists: list) -> tuple[list, list]:
    """Return (live, others): live playlists are the ones with the live tag."""
    live = [p for p in playlists if is_live(p)]
    return live, [p for p in playlists if not is_live(p)]


def playlist_name(name: str, prefix: str) -> str:
    """The name a live playlist is created with: sanitized and always prefixed.

    A hand-edited name gets LIVE_PLAYLIST_PREFIX back, so all live playlists
    read alike. Sanitizing strips the prefix's trailing space, hence the
    comparison without it.
    """
    name = sanitize_for_filename(sanitize_untrusted_text(name))
    rest = name.removeprefix(prefix.strip()).strip()
    if not rest:
        raise LiveError(t("The playlist name is empty."))
    return prefix + rest


def create_live_playlist(
    jellyfin: JellyfinClient,
    user: JellyfinUser,
    mix: LiveMix,
    name: str,
    prefix: str,
    public: bool = False,
) -> CreatedPlaylist:
    """Create the playlist for user; a public one is visible to every user."""
    item_ids = [song.jellyfin_item_id for song in mix.matched]
    if not item_ids:
        raise LiveError(t("None of the songs is in the library; no playlist created."))
    name = playlist_name(name, prefix)
    existing = {p.name for p in jellyfin.get_playlists_for_user(user.id, media_types=None)}
    name = unique_name(name, existing)
    playlist_id = jellyfin.create_playlist(user.id, name, item_ids, public=public)
    logger.info(
        "event=live_playlist_created user=%s playlist=%s playlist_id=%s tracks=%s concerts=%s",
        sanitize_untrusted_text(user.name),
        name,
        playlist_id,
        len(item_ids),
        len(mix.concerts),
    )
    # The playlist exists either way: a failed step is reported, never undone.
    warnings = []
    try:
        jellyfin.add_managed_tag(user.id, playlist_id, LIVE_TAG)
    except Exception as exc:  # noqa: BLE001
        warnings.append(
            t("The live tag is missing, so prune and purge do not protect it: {error}", error=exc)
        )
        logger.warning("event=live_tag_failed playlist_id=%s error=%s", playlist_id, exc)
    try:
        jellyfin.set_overview(user.id, playlist_id, overview_text(mix))
    except Exception as exc:  # noqa: BLE001
        warnings.append(
            t("The description with the setlist.fm source is missing: {error}", error=exc)
        )
        logger.warning("event=live_overview_failed playlist_id=%s error=%s", playlist_id, exc)
    warning = " ".join([t("Playlist created."), *warnings]) if warnings else None
    return CreatedPlaylist(playlist_id, name, len(item_ids), warning)
