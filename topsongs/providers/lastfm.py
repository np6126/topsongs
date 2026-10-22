from __future__ import annotations

import logging
import re
from typing import NamedTuple

import httpx

from ..http import REQUEST_ERRORS, Throttle, send_with_retries
from ..models import Discography, DiscographyAlbum, ProviderTrack
from ..normalize import normalize_name
from ..sanitize import sanitize_untrusted_text
from .base import TopSongsProvider

logger = logging.getLogger(__name__)
TOP_LEVEL_RESPONSE_RE = re.compile(r'^\s*\{\s*"(toptracks|topalbums|album|error)"\s*:')

# Album titles that are almost never studio albums on Last.fm. Used to
# approximate the "studio albums + EPs" scope, since Last.fm exposes no
# release-type metadata. EPs are intentionally kept.
_NON_STUDIO_ALBUM_RE = re.compile(
    r"\b(greatest hits|best of|the collection|anthology|essential|"
    r"compilation|live at|live in|live from|in concert|unplugged|"
    r"b[\s-]?sides|rarities|outtakes|demos|remix(?:es|ed)?|"
    r"singles collection|box set)\b",
    re.IGNORECASE,
)

# Edition/reissue noise stripped before grouping album variants together.
_EDITION_NOISE_RE = re.compile(
    r"\b(deluxe|expanded|remaster(?:ed)?|anniversary|edition|version|"
    r"explicit|clean|bonus|special|collector'?s?|reissue|mono|stereo|"
    r"\d{4})\b",
    re.IGNORECASE,
)
_BRACKETED_RE = re.compile(r"[\(\[][^\)\]]*[\)\]]")


class _RawAlbum(NamedTuple):
    title: str
    mbid: str
    playcount: int


class LastFmError(RuntimeError):
    pass


class LastFmRateLimitError(LastFmError):
    pass


class LastFmNoTopTracksError(LastFmError):
    pass


class LastFmProvider(TopSongsProvider):
    base_url = "https://ws.audioscrobbler.com/2.0/"

    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        max_tracks: int = 200,
        min_request_interval: float = 0.0,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._max_tracks = max_tracks
        self._throttle = Throttle(min_request_interval)
        # One pooled client per run: httpx.Client is thread-safe and reuses
        # keep-alive connections across requests instead of dialing each time.
        self._client = httpx.Client(timeout=self._timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LastFmProvider":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    @property
    def name(self) -> str:
        return "lastfm"

    def get_top_tracks(self, artist_name: str) -> list[ProviderTrack]:
        params = {
            "method": "artist.gettoptracks",
            "artist": artist_name,
            "api_key": self._api_key,
            "format": "json",
            "autocorrect": "1",
            "limit": str(self._max_tracks),
        }
        tracks = self._request_entries(params, artist_name, "toptracks", "track")
        if not tracks:
            raise LastFmNoTopTracksError(f"artist={artist_name} message=no_top_tracks")

        results: list[ProviderTrack] = []
        for entry in tracks[: self._max_tracks]:
            title = sanitize_untrusted_text(str(entry.get("name", "")).strip())
            if not title:
                continue
            results.append(
                ProviderTrack(
                    title=title,
                    rank=int(entry.get("@attr", {}).get("rank", len(results) + 1)),
                    listeners=_to_int(entry.get("listeners")),
                    playcount=_to_int(entry.get("playcount")),
                    mbid=(entry.get("mbid") or None),
                    url=(entry.get("url") or None),
                )
            )

        logger.debug(
            "provider=lastfm artist=%s returned_tracks=%s",
            sanitize_untrusted_text(artist_name),
            len(results),
        )
        return results

    def get_discography(
        self,
        artist_name: str,
        *,
        include_all_types: bool = False,
        top_albums_limit: int = 100,
    ) -> Discography:
        raw_albums = self._get_top_albums(artist_name, top_albums_limit)

        # Group edition variants (Deluxe, Remastered, ...) under one base name
        # and keep the most-played variant. Done before fetching tracklists so
        # album.getinfo is only called once per real album.
        by_base: dict[str, _RawAlbum] = {}
        for album in raw_albums:
            if not include_all_types and not _is_studio_album(album.title):
                continue
            base = _album_base_key(album.title)
            if not base:
                continue
            existing = by_base.get(base)
            if existing is None or album.playcount > existing.playcount:
                by_base[base] = album

        albums: list[DiscographyAlbum] = []
        for album in sorted(by_base.values(), key=lambda a: a.playcount, reverse=True):
            tracks = self._get_album_tracks(artist_name, album.title, album.mbid)
            if not tracks:
                continue
            albums.append(
                DiscographyAlbum(
                    title=_clean_display_title(album.title),
                    mbid=album.mbid or None,
                    playcount=album.playcount,
                    tracks=tracks,
                )
            )

        logger.debug(
            "provider=lastfm artist=%s discography_albums=%s",
            sanitize_untrusted_text(artist_name),
            len(albums),
        )
        return Discography(artist_name=artist_name, albums=albums)

    def _get_top_albums(self, artist_name: str, limit: int) -> list[_RawAlbum]:
        params = {
            "method": "artist.gettopalbums",
            "artist": artist_name,
            "api_key": self._api_key,
            "format": "json",
            "autocorrect": "1",
            "limit": str(limit),
        }
        entries = self._request_entries(params, artist_name, "topalbums", "album")

        results: list[_RawAlbum] = []
        for entry in entries:
            title = sanitize_untrusted_text(str(entry.get("name", "")).strip())
            if not title or title.lower() in {"(null)", "null"}:
                continue
            results.append(
                _RawAlbum(
                    title=title,
                    mbid=(entry.get("mbid") or "").strip(),
                    playcount=_to_int(entry.get("playcount")) or 0,
                )
            )
        return results

    def _get_album_tracks(self, artist_name: str, album_title: str, mbid: str) -> list[str]:
        params = {
            "method": "album.getinfo",
            "api_key": self._api_key,
            "format": "json",
            "autocorrect": "1",
        }
        if mbid:
            params["mbid"] = mbid
        else:
            params["artist"] = artist_name
            params["album"] = album_title

        try:
            payload = self._request_json(params, artist_name)
        except LastFmRateLimitError:
            raise
        except LastFmError as exc:
            logger.warning(
                "provider=lastfm event=album_getinfo_failed album=%s error=%s",
                sanitize_untrusted_text(album_title),
                exc,
            )
            return []

        if "error" in payload:
            return []

        track_entries = payload.get("album", {}).get("tracks", {}).get("track", [])
        if isinstance(track_entries, dict):
            track_entries = [track_entries]

        tracks: list[str] = []
        for entry in track_entries:
            title = sanitize_untrusted_text(str(entry.get("name", "")).strip())
            if title:
                tracks.append(title)
        return tracks

    def _request_entries(
        self, params: dict[str, str], artist_name: str, container: str, item: str
    ) -> list:
        # Last.fm collapses a single-element list to a bare object, so the
        # result is always normalized back to a list.
        payload = self._request_json(params, artist_name)
        _raise_for_payload_error(payload, artist_name)
        entries = payload.get(container, {}).get(item, [])
        if isinstance(entries, dict):
            return [entries]
        return entries

    def _request_json(self, params: dict[str, str], artist_name: str) -> dict:
        def send() -> httpx.Response:
            self._throttle.wait()
            response = self._client.get(self.base_url, params=params)
            response.raise_for_status()
            return response

        try:
            response = send_with_retries(
                send,
                max_retries=self._max_retries,
                backoff_seconds=self._retry_backoff_seconds,
                log_context=f"provider=lastfm artist={sanitize_untrusted_text(artist_name)}",
            )
        except REQUEST_ERRORS as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                raise LastFmRateLimitError(f"artist={artist_name} message=http_429") from exc
            raise LastFmError(
                f"artist={sanitize_untrusted_text(artist_name)} "
                f"message=request_failed error={exc}"
            ) from exc
        _validate_raw_response_prefix(response.text, artist_name)
        return response.json()

def _raise_for_payload_error(payload: dict, artist_name: str) -> None:
    if "error" not in payload:
        return
    message = payload.get("message", "unknown Last.fm error")
    error_code = int(payload.get("error", 0) or 0)
    if error_code in {11, 16, 26, 29}:
        raise LastFmRateLimitError(f"artist={artist_name} message={message}")
    raise LastFmError(f"artist={artist_name} message={message}")


def _is_studio_album(title: str) -> bool:
    """Approximate whether a Last.fm album entry is a studio album or EP.

    Last.fm exposes no release-type metadata, so compilations, live albums and
    singles collections are detected by name. EPs are deliberately kept.
    """
    return not _NON_STUDIO_ALBUM_RE.search(title)


def _album_base_key(title: str) -> str:
    """Collapse edition variants of the same album to one comparable key."""
    text = _BRACKETED_RE.sub(" ", title)
    text = re.sub(r"\s-\s.*$", "", text)
    text = _EDITION_NOISE_RE.sub(" ", text)
    return normalize_name(text)


def _clean_display_title(title: str) -> str:
    cleaned = _BRACKETED_RE.sub("", title)
    cleaned = re.sub(r"\s-\s.*$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or title.strip()


def _to_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _validate_raw_response_prefix(raw_text: str, artist_name: str) -> None:
    if not TOP_LEVEL_RESPONSE_RE.match(raw_text):
        raise LastFmError(
            f"artist={sanitize_untrusted_text(artist_name)} message=unexpected_response_prefix"
        )
