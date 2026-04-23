from __future__ import annotations

import logging
import re
import time

import httpx

from ..models import ProviderTrack
from ..sanitize import sanitize_untrusted_text
from .base import TopSongsProvider

logger = logging.getLogger(__name__)
TOP_LEVEL_RESPONSE_RE = re.compile(r'^\s*\{\s*"(toptracks|error)"\s*:')


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
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._max_tracks = max_tracks

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
        payload = self._request_json(params, artist_name)

        if "error" in payload:
            message = payload.get("message", "unknown Last.fm error")
            error_code = int(payload.get("error", 0) or 0)
            if error_code in {11, 16, 26, 29}:
                raise LastFmRateLimitError(f"artist={artist_name} message={message}")
            raise LastFmError(f"artist={artist_name} message={message}")

        tracks = payload.get("toptracks", {}).get("track", [])
        if isinstance(tracks, dict):
            tracks = [tracks]
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

    def _request_json(self, params: dict[str, str], artist_name: str) -> dict:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.get(self.base_url, params=params)
                    if response.status_code == 429:
                        raise LastFmRateLimitError(f"artist={artist_name} message=http_429")
                    response.raise_for_status()
                    _validate_raw_response_prefix(response.text, artist_name)
                    return response.json()
            except LastFmRateLimitError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                should_retry = attempt < self._max_retries and _is_retryable_http_error(exc)
                logger.warning(
                    "provider=lastfm artist=%s attempt=%s retry=%s error=%s",
                    sanitize_untrusted_text(artist_name),
                    attempt + 1,
                    should_retry,
                    exc,
                )
                if not should_retry:
                    break
                time.sleep(self._retry_backoff_seconds * (attempt + 1))

        raise LastFmError(
            f"artist={sanitize_untrusted_text(artist_name)} "
            f"message=request_failed error={last_error}"
        )


def _to_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _is_retryable_http_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def _validate_raw_response_prefix(raw_text: str, artist_name: str) -> None:
    if not TOP_LEVEL_RESPONSE_RE.match(raw_text):
        raise LastFmError(
            f"artist={sanitize_untrusted_text(artist_name)} message=unexpected_response_prefix"
        )
