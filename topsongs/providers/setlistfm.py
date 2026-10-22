"""setlist.fm API client for the on-demand live playlists.

API reference: https://api.setlist.fm/docs/1.0/ — the key goes in the
``x-api-key`` header, JSON is requested via ``Accept``. A standard key allows
about 2 requests a second and 1,440 a day, so requests are spaced 0.5 s apart.
Responses are kept for 10 minutes: the API terms allow caching only for short
periods, and that covers the list, preview and create steps of one playlist.
"""
from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from datetime import date, datetime

import httpx

from ..http import REQUEST_ERRORS, Throttle, send_with_retries
from ..i18n import t
from ..models import Concert, ConcertFilter, ConcertSong, SetlistArtist
from ..sanitize import sanitize_untrusted_text

BASE_URL = "https://api.setlist.fm/rest/1.0"

# A setlist page URL ends in "-<id>.html", e.g.
# https://www.setlist.fm/setlist/metallica/2026/olympiastadion-berlin-germany-3bd6c4f8.html
_SETLIST_URL_ID = re.compile(r"-([0-9a-f]{6,10})\.html?(?:[?#].*)?$", re.IGNORECASE)
_SETLIST_ID = re.compile(r"^[0-9a-f]{6,10}$", re.IGNORECASE)


class SetlistFmError(RuntimeError):
    pass


def parse_setlist_ref(value: str) -> str:
    """Return the setlist id from a bare id or a setlist.fm setlist URL."""
    text = value.strip()
    if _SETLIST_ID.match(text):
        return text.lower()
    found = _SETLIST_URL_ID.search(text)
    if found and "setlist.fm/" in text:
        return found.group(1).lower()
    raise ValueError(t("Not a setlist.fm setlist id or link: {value}", value=value))


class SetlistFmClient:
    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        min_request_interval: float = 0.5,
        cache_ttl_seconds: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._throttle = Throttle(min_request_interval, clock)
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._responses: dict[str, tuple[float, dict | None]] = {}
        self._concerts: dict[str, tuple[float, Concert]] = {}
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={"x-api-key": api_key, "Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SetlistFmClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    # ------------------------------------------------------------------ #
    # Endpoints
    # ------------------------------------------------------------------ #

    def artist_setlists(self, mbid: str) -> list[Concert]:
        """The artist's 20 newest setlists, upcoming concerts without songs included."""
        payload = self._get(f"/artist/{mbid}/setlists", {"p": "1"})
        return self._concerts_from(payload)

    def search_setlists(self, mbid: str, concert_filter: ConcertFilter) -> list[Concert]:
        """The artist's newest 20 setlists that match the filter."""
        params = {
            "artistMbid": mbid,
            "p": "1",
            "tourName": concert_filter.tour,
            "year": str(concert_filter.year) if concert_filter.year else None,
            "venueName": concert_filter.venue,
            "cityName": concert_filter.city,
            "countryCode": concert_filter.country.upper() if concert_filter.country else None,
        }
        params = {key: value for key, value in params.items() if value}
        return self._concerts_from(self._get("/search/setlists", params))

    def setlist(self, setlist_id: str) -> Concert:
        with self._lock:
            cached = self._concerts.get(setlist_id)
            if cached and cached[0] > self._clock():
                return cached[1]
        payload = self._get(f"/setlist/{setlist_id}", {})
        concert = parse_concert(payload) if payload else None
        if concert is None:
            raise SetlistFmError(t("setlist.fm has no setlist {id}.", id=setlist_id))
        return concert

    def search_artists(self, name: str) -> list[SetlistArtist]:
        payload = self._get(
            "/search/artists", {"artistName": name, "sort": "relevance", "p": "1"}
        )
        artists = []
        for raw in (payload or {}).get("artist") or []:
            mbid = raw.get("mbid")
            artist_name = sanitize_untrusted_text(str(raw.get("name") or ""))
            if mbid and artist_name:
                artists.append(
                    SetlistArtist(
                        mbid=mbid,
                        name=artist_name,
                        disambiguation=sanitize_untrusted_text(
                            str(raw.get("disambiguation") or "")
                        )
                        or None,
                    )
                )
        return artists

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #

    def _concerts_from(self, payload: dict | None) -> list[Concert]:
        concerts = [
            concert
            for raw in (payload or {}).get("setlist") or []
            if (concert := parse_concert(raw)) is not None
        ]
        self._remember(concerts)
        return concerts

    def _remember(self, concerts: list[Concert]) -> None:
        now = self._clock()
        with self._lock:
            _evict(self._concerts, now)
            for concert in concerts:
                self._concerts[concert.id] = (now + self._cache_ttl_seconds, concert)

    def _get(self, path: str, params: dict[str, str]) -> dict | None:
        """GET a JSON payload; None when setlist.fm answers 404 (nothing found)."""
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        with self._lock:
            cached = self._responses.get(key)
            if cached and cached[0] > self._clock():
                return cached[1]

        payload = self._request(path, params)
        now = self._clock()
        with self._lock:
            _evict(self._responses, now)
            self._responses[key] = (now + self._cache_ttl_seconds, payload)
        return payload

    def _request(self, path: str, params: dict[str, str]) -> dict | None:
        def send() -> dict | None:
            self._throttle.wait()
            response = self._client.get(BASE_URL + path, params=params)
            if response.status_code == 404:  # nothing found, not a failure
                return None
            response.raise_for_status()
            return response.json()

        try:
            return send_with_retries(
                send,
                max_retries=self._max_retries,
                backoff_seconds=self._retry_backoff_seconds,
                log_context=f"service=setlistfm path={path}",
                # setlist.fm limits requests per second, so a short wait clears a 429.
                retry_statuses=frozenset({429}),
            )
        except httpx.HTTPStatusError as exc:
            raise SetlistFmError(_status_message(exc.response.status_code)) from exc
        except REQUEST_ERRORS as exc:
            raise SetlistFmError(t("setlist.fm is not reachable: {error}", error=exc)) from exc

def _evict(cache: dict, now: float) -> None:
    """Drop expired entries so a long-running web server keeps only the working set."""
    for key in [key for key, (expires, _) in cache.items() if expires <= now]:
        del cache[key]


def _status_message(status: int) -> str:
    if status in (401, 403):
        return t("setlist.fm rejects the API key (check SETLISTFM_API_KEY).")
    if status == 429:
        return t(
            "setlist.fm limit reached (2 requests a second, 1,440 a day). Try again later."
        )
    return t("setlist.fm answers with HTTP {status}.", status=status)


def parse_concert(raw: dict) -> Concert | None:
    setlist_id = raw.get("id")
    if not setlist_id:
        return None
    venue = raw.get("venue") or {}
    city = venue.get("city") or {}
    # The JSON nests sets as {"sets": {"set": [...]}}; the docs show a bare "set".
    sets = (raw.get("sets") or {}).get("set") or raw.get("set") or []
    songs = []
    for raw_set in sets:
        encore = bool(raw_set.get("encore"))
        for raw_song in raw_set.get("song") or []:
            title = sanitize_untrusted_text(str(raw_song.get("name") or ""))
            # Tape intros and outros were never played; an empty name is a
            # song nobody identified yet.
            if not title or raw_song.get("tape"):
                continue
            cover = (raw_song.get("cover") or {}).get("name")
            songs.append(
                ConcertSong(
                    title=title,
                    encore=encore,
                    cover_artist=sanitize_untrusted_text(cover) if cover else None,
                )
            )
    return Concert(
        id=str(setlist_id),
        url=raw.get("url") or None,
        event_date=_parse_date(raw.get("eventDate")),
        artist_name=sanitize_untrusted_text(str((raw.get("artist") or {}).get("name") or "")),
        venue_id=venue.get("id") or None,
        venue_name=sanitize_untrusted_text(str(venue.get("name") or "")),
        city=sanitize_untrusted_text(str(city.get("name") or "")) or None,
        country_code=((city.get("country") or {}).get("code") or None),
        tour=sanitize_untrusted_text(str((raw.get("tour") or {}).get("name") or "")) or None,
        songs=songs,
    )


def _parse_date(value: object) -> date | None:
    try:
        return datetime.strptime(str(value), "%d-%m-%Y").date()
    except ValueError:
        return None
