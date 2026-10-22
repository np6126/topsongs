import httpx
import pytest

from topsongs.http import Throttle, send_with_retries
from topsongs.jellyfin import JellyfinClient
from topsongs.providers.lastfm import LastFmProvider, LastFmRateLimitError

REQUEST = httpx.Request("GET", "http://x/")
OK = httpx.Response(200, request=REQUEST)


def _status_error(status: int, headers=None) -> httpx.HTTPStatusError:
    response = httpx.Response(status, headers=headers, request=REQUEST)
    return httpx.HTTPStatusError(str(status), request=REQUEST, response=response)


def _sender(*outcomes):
    """send() that raises or returns the given outcomes in order."""
    queue = list(outcomes)

    def send():
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return send


def _retry(send, max_retries=2, backoff_seconds=0.0, **kwargs):
    return send_with_retries(
        send, max_retries=max_retries, backoff_seconds=backoff_seconds, log_context="t", **kwargs
    )


@pytest.mark.parametrize(
    "exc,retry_statuses,retried",
    [
        (httpx.RemoteProtocolError("peer closed"), (), True),
        (httpx.ConnectError("refused"), (), True),
        (httpx.ReadTimeout("slow"), (), True),
        (_status_error(503), (), True),
        (_status_error(404), (), False),
        (_status_error(429), (), False),
        (_status_error(429), (429,), True),
    ],
)
def test_which_failures_are_sent_again(sleeps, exc, retry_statuses, retried):
    send = _sender(exc, OK)
    if retried:
        assert _retry(send, retry_statuses=frozenset(retry_statuses)) is OK
    else:
        with pytest.raises(type(exc)):
            _retry(send, retry_statuses=frozenset(retry_statuses))


def test_retries_with_growing_backoff_then_succeeds(sleeps, caplog):
    result = send_with_retries(
        _sender(_status_error(502), httpx.ConnectError("down"), OK),
        max_retries=2,
        backoff_seconds=1.5,
        log_context="service=x",
    )

    assert result is OK
    assert sleeps == [1.5, 3.0]
    assert [r.getMessage() for r in caplog.records] == [
        "service=x attempt=1 retry=True error=502",
        "service=x attempt=2 retry=True error=down",
    ]


def test_gives_up_after_max_retries(sleeps):
    with pytest.raises(httpx.HTTPStatusError):
        _retry(_sender(*[_status_error(500)] * 3))

    assert len(sleeps) == 2


def test_non_retryable_error_propagates_at_once(sleeps):
    with pytest.raises(httpx.HTTPStatusError):
        _retry(_sender(_status_error(400)), max_retries=5, backoff_seconds=1)

    assert sleeps == []


def test_retry_after_is_honoured_and_capped(sleeps):
    send = _sender(
        _status_error(503, {"Retry-After": "2"}), _status_error(503, {"Retry-After": "99"}), OK
    )

    _retry(send, backoff_seconds=5)

    assert sleeps == [2.0, 10.0]


def test_throttle_spaces_calls_and_is_off_at_zero(sleeps):
    now = [100.0]
    throttle = Throttle(0.5, clock=lambda: now[0])

    throttle.wait()
    now[0] += 0.2
    throttle.wait()
    Throttle(0).wait()

    assert sleeps == [pytest.approx(0.3)]


# --------------------------------------------------------------------------- #
# The clients on top of it
# --------------------------------------------------------------------------- #

def test_jellyfin_retries_server_errors_and_reports_the_final_failure(sleeps):
    statuses = [503, 200]
    client = JellyfinClient(base_url="http://jellyfin", api_key="k", retry_backoff_seconds=0)
    client._client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(statuses.pop(0), json={}))
    )

    assert client._get("/Users", {}) == {}

    client._client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(RuntimeError, match="service=jellyfin .*request_failed"):
        client._get("/Users", {})


def test_lastfm_rate_limit_is_not_retried(sleeps):
    calls = []
    provider = LastFmProvider(api_key="k")
    provider._client = httpx.Client(
        transport=httpx.MockTransport(lambda r: calls.append(1) or httpx.Response(429))
    )

    with pytest.raises(LastFmRateLimitError):
        provider._request_json({"method": "x"}, "Artist")

    assert len(calls) == 1 and sleeps == []
