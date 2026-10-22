"""HTTP plumbing shared by the Jellyfin, Last.fm and setlist.fm clients.

Which failures are worth sending again, the retry loop, and request spacing.
Each client keeps only its own rules on top: what a status code means for its
API and how a final failure is reported.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

# Failures of the connection itself; sending the request again may succeed.
TRANSPORT_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
REQUEST_ERRORS = (*TRANSPORT_ERRORS, httpx.HTTPStatusError)

_MAX_RETRY_AFTER_SECONDS = 10.0

T = TypeVar("T")


def send_with_retries(
    send: Callable[[], T],
    *,
    max_retries: int,
    backoff_seconds: float,
    log_context: str,
    retry_statuses: frozenset[int] = frozenset(),
) -> T:
    """Return send()'s result, sending again on transport errors, 5xx and retry_statuses.

    send raises an httpx error for a failed request, e.g. via raise_for_status.
    The wait grows with each attempt unless the server names one in Retry-After
    (capped at 10 s). Each failure is logged after log_context. Once the retries
    are used up, the last error propagates.
    """
    attempt = 0
    while True:
        try:
            return send()
        except REQUEST_ERRORS as exc:
            attempt += 1
            retry = attempt <= max_retries and _is_retryable(exc, retry_statuses)
            logger.warning("%s attempt=%s retry=%s error=%s", log_context, attempt, retry, exc)
            if not retry:
                raise
            time.sleep(_retry_after(exc) or backoff_seconds * attempt)


def _is_retryable(exc: Exception, retry_statuses: frozenset[int]) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status >= 500 or status in retry_statuses
    # A transport error. RemoteProtocolError surfaces when a pooled keep-alive
    # connection was closed server-side while idle; the retry dials a fresh one.
    return True


def _retry_after(exc: Exception) -> float | None:
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    try:
        seconds = float(exc.response.headers.get("Retry-After", ""))
    except ValueError:
        return None
    return min(_MAX_RETRY_AFTER_SECONDS, max(0.0, seconds))


class Throttle:
    """Spaces calls to wait() at least `interval` seconds apart, across threads."""

    def __init__(self, interval: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._interval = interval
        self._clock = clock
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> None:
        if self._interval <= 0:
            return
        # Sleeping under the lock is intended: it makes the spacing hold across
        # threads, not only within one caller.
        with self._lock:
            if self._last is not None:
                remaining = self._interval - (self._clock() - self._last)
                if remaining > 0:
                    time.sleep(remaining)
            self._last = self._clock()
