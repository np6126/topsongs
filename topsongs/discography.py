from __future__ import annotations

import logging
import time
from pathlib import Path

from .models import AlbumGap, ArtistGap, Discography, JellyfinTrack
from .normalize import normalize_name

logger = logging.getLogger(__name__)

# Part of the cache filename. Bump whenever the discography fetch logic changes
# so that caches written by an older version are ignored instead of reused.
_CACHE_SCHEMA = "v3"

# Minimum title length for single-character typo matching. Short titles are
# excluded so that genuinely different songs are never fuzzy-merged.
_MIN_FUZZY_LEN = 10


def compute_artist_gap(
    artist_name: str,
    local_tracks: list[JellyfinTrack],
    discography: Discography,
) -> ArtistGap:
    """Compare a local library against a reference discography.

    A discography track counts as owned when the user has any local track of
    this artist with a matching normalized title, regardless of which local
    album it sits on. Single-character typos in Last.fm's crowd-sourced track
    titles are tolerated so misspelled duplicates are not flagged as missing.
    """
    owned = {normalize_name(track.name) for track in local_tracks}
    owned.discard("")

    albums: list[AlbumGap] = []
    seen_albums: set[str] = set()
    for album in discography.albums:
        album_key = normalize_name(album.title)
        if album_key and album_key in seen_albums:
            continue
        if album_key:
            seen_albums.add(album_key)

        missing: list[str] = []
        owned_count = 0
        seen_tracks: set[str] = set()
        for track_title in album.tracks:
            track_key = normalize_name(track_title)
            if not track_key or track_key in seen_tracks:
                continue
            seen_tracks.add(track_key)
            if track_key in owned or _fuzzy_owned(track_key, owned):
                owned_count += 1
            else:
                missing.append(track_title)

        if not seen_tracks:
            continue

        albums.append(
            AlbumGap(
                title=album.title,
                year=album.year,
                total_tracks=len(seen_tracks),
                owned_count=owned_count,
                missing_titles=missing,
            )
        )

    return ArtistGap(artist_name=artist_name, albums=_collapse_typo_albums(albums))


def _within_one_edit(a: str, b: str) -> bool:
    """True if a and b are equal or differ by one insert, delete or substitution."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1

    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    i = j = 0
    edited = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
        elif edited:
            return False
        else:
            edited = True
            j += 1
    return True


def _has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def _fuzzy_owned(track_key: str, owned: set[str]) -> bool:
    """True if an owned track differs from track_key by a single typo.

    Only long, digit-free titles qualify, so genuinely different songs and
    numbered/sequel tracks ("chapter 1" vs "chapter 2") are never merged.
    """
    if len(track_key) < _MIN_FUZZY_LEN or _has_digit(track_key):
        return False
    return any(
        len(owned_key) >= _MIN_FUZZY_LEN
        and not _has_digit(owned_key)
        and _within_one_edit(track_key, owned_key)
        for owned_key in owned
    )


def _collapse_typo_albums(albums: list[AlbumGap]) -> list[AlbumGap]:
    """Drop a fully-owned album whose title is a single-typo variant of an
    album already kept. Last.fm sometimes lists the same release twice with a
    misspelling; collapsing only complete albums can never hide a missing track.
    """
    kept: list[AlbumGap] = []
    kept_keys: list[str] = []
    for album in albums:
        key = normalize_name(album.title)
        if album.is_complete and any(_within_one_edit(key, other) for other in kept_keys):
            continue
        kept.append(album)
        kept_keys.append(key)
    return kept


class DiscographyCache:
    """On-disk cache of fetched discographies, keyed by artist name and scope."""

    def __init__(self, cache_dir: Path, ttl_seconds: float) -> None:
        self._cache_dir = cache_dir
        self._ttl_seconds = ttl_seconds

    def _path(self, artist_name: str, scope: str) -> Path:
        slug = normalize_name(artist_name).replace(" ", "_") or "_unknown_"
        return self._cache_dir / f"{slug}__{scope}__{_CACHE_SCHEMA}.json"

    def get(self, artist_name: str, scope: str) -> Discography | None:
        path = self._path(artist_name, scope)
        try:
            age = time.time() - path.stat().st_mtime
        except FileNotFoundError:
            return None
        if age > self._ttl_seconds:
            return None
        try:
            return Discography.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("event=discography_cache_read_failed path=%s error=%s", path, exc)
            return None

    def put(self, artist_name: str, scope: str, discography: Discography) -> None:
        path = self._path(artist_name, scope)
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(discography.model_dump_json(), encoding="utf-8")
        except OSError as exc:
            logger.warning("event=discography_cache_write_failed path=%s error=%s", path, exc)
