from datetime import date

import httpx
import pytest

from topsongs.models import ConcertFilter
from topsongs.providers.setlistfm import (
    SetlistFmClient,
    SetlistFmError,
    parse_concert,
    parse_setlist_ref,
)


def raw_setlist(setlist_id="3bd6c4f8", **over):
    raw = {
        "id": setlist_id,
        "eventDate": "12-10-2026",
        "url": f"https://www.setlist.fm/setlist/metallica/2026/olympiastadion-{setlist_id}.html",
        "artist": {"mbid": "65f4f0c5", "name": "Metallica"},
        "venue": {
            "id": "venue-1",
            "name": "Olympiastadion",
            "city": {"name": "Berlin", "country": {"code": "DE", "name": "Germany"}},
        },
        "tour": {"name": "M72 World Tour"},
        "sets": {
            "set": [
                {
                    "song": [
                        {"name": "The Ecstasy of Gold", "tape": True},
                        {"name": "Creeping Death"},
                        {"name": ""},
                        {"name": "Whiskey in the Jar", "cover": {"name": "Thin Lizzy"}},
                    ]
                },
                {"encore": 1, "song": [{"name": "Enter Sandman"}]},
            ]
        },
    }
    raw.update(over)
    return raw


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def test_parse_concert_flattens_sets_and_drops_tape_and_unnamed_songs():
    concert = parse_concert(raw_setlist())

    assert [s.title for s in concert.songs] == [
        "Creeping Death",
        "Whiskey in the Jar",
        "Enter Sandman",
    ]
    assert [s.encore for s in concert.songs] == [False, False, True]
    assert concert.songs[1].cover_artist == "Thin Lizzy"
    assert concert.event_date == date(2026, 10, 12)
    assert (concert.venue_name, concert.city, concert.country_code) == (
        "Olympiastadion",
        "Berlin",
        "DE",
    )
    assert concert.tour == "M72 World Tour"
    assert concert.artist_name == "Metallica"


def test_parse_concert_accepts_bare_set_list_and_missing_parts():
    raw = {"id": "abc123", "artist": {"name": "X"}, "set": [{"song": [{"name": "Song"}]}]}

    concert = parse_concert(raw)

    assert [s.title for s in concert.songs] == ["Song"]
    assert concert.event_date is None and concert.tour is None and concert.venue_name == ""


def test_upcoming_concert_has_no_songs():
    concert = parse_concert(raw_setlist(sets={"set": []}))

    assert concert.songs == []


def test_parse_concert_strips_control_characters():
    raw = raw_setlist(sets={"set": [{"song": [{"name": "Evil\x1b[31m Song\n"}]}]})

    assert parse_concert(raw).songs[0].title == "Evil Song"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("3bd6c4f8", "3bd6c4f8"),
        ("  63AD8A1F ", "63ad8a1f"),
        (
            "https://www.setlist.fm/setlist/metallica/2026/olympiastadion-berlin-germany-3bd6c4f8.html",
            "3bd6c4f8",
        ),
    ],
)
def test_parse_setlist_ref(value, expected):
    assert parse_setlist_ref(value) == expected


@pytest.mark.parametrize("value", ["", "metallica", "https://example.com/x-3bd6c4f8.html"])
def test_parse_setlist_ref_rejects_other_input(value):
    with pytest.raises(ValueError):
        parse_setlist_ref(value)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

def _client(handler, **kwargs) -> SetlistFmClient:
    kwargs.setdefault("min_request_interval", 0)
    client = SetlistFmClient(api_key="key", retry_backoff_seconds=0, **kwargs)
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"x-api-key": "key", "Accept": "application/json"},
    )
    return client


def test_artist_setlists_requests_first_page_with_key():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"setlist": [raw_setlist()]})

    concerts = _client(handler).artist_setlists("mbid-1")

    assert [c.id for c in concerts] == ["3bd6c4f8"]
    assert seen[0].url.path == "/rest/1.0/artist/mbid-1/setlists"
    assert seen[0].url.params["p"] == "1"
    assert seen[0].headers["x-api-key"] == "key"
    assert seen[0].headers["accept"] == "application/json"


def test_responses_and_listed_setlists_are_cached():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"setlist": [raw_setlist()]})

    client = _client(handler)
    client.artist_setlists("mbid-1")
    client.artist_setlists("mbid-1")
    concert = client.setlist("3bd6c4f8")

    assert calls == ["/rest/1.0/artist/mbid-1/setlists"]
    assert concert.venue_name == "Olympiastadion"


def test_cache_expires_after_ttl():
    now = [0.0]
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"setlist": []})

    client = _client(handler, clock=lambda: now[0], cache_ttl_seconds=600)
    client.artist_setlists("m")
    now[0] = 601
    client.artist_setlists("m")

    assert len(calls) == 2


def test_not_found_means_no_concerts():
    client = _client(lambda request: httpx.Response(404, json={"message": "not found"}))

    assert client.search_setlists("m", ConcertFilter(tour="Nope")) == []


def test_unknown_setlist_raises():
    client = _client(lambda request: httpx.Response(404))

    with pytest.raises(SetlistFmError):
        client.setlist("deadbeef")


def test_search_setlists_maps_the_filter_to_search_parameters():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"setlist": []})

    concert_filter = ConcertFilter(
        tour="M72", year=2026, venue="Olympiastadion", city=" Berlin ", country="de"
    )
    _client(handler).search_setlists("mbid-1", concert_filter)
    _client(handler).search_setlists("mbid-1", ConcertFilter(tour="M72", city="  "))

    assert seen == [
        {
            "artistMbid": "mbid-1",
            "p": "1",
            "tourName": "M72",
            "year": "2026",
            "venueName": "Olympiastadion",
            "cityName": "Berlin",
            "countryCode": "DE",
        },
        {"artistMbid": "mbid-1", "p": "1", "tourName": "M72"},
    ]


def test_rejected_key_raises_clear_error():
    client = _client(lambda request: httpx.Response(403))

    with pytest.raises(SetlistFmError, match="API-Key"):
        client.artist_setlists("m")


def test_rate_limit_is_retried(sleeps):
    responses = [httpx.Response(429), httpx.Response(200, json={"setlist": [raw_setlist()]})]

    client = _client(lambda request: responses.pop(0))

    assert len(client.artist_setlists("m")) == 1


def test_lasting_rate_limit_raises_limit_message(sleeps):
    client = _client(lambda request: httpx.Response(429))

    with pytest.raises(SetlistFmError, match="Limit"):
        client.artist_setlists("m")


def test_requests_are_spaced(sleeps):
    client = _client(
        lambda r: httpx.Response(200, json={"setlist": []}),
        min_request_interval=0.5,
        clock=lambda: 10.0,
    )

    client.artist_setlists("a")
    client.artist_setlists("b")

    assert sleeps == [0.5]


def test_search_artists_parses_candidates():
    payload = {
        "artist": [
            {"mbid": "m1", "name": "Ghost", "disambiguation": "Swedish rock band"},
            {"mbid": "m2", "name": "Ghost", "disambiguation": ""},
            {"name": "no mbid"},
        ]
    }
    client = _client(lambda request: httpx.Response(200, json=payload))

    artists = client.search_artists("Ghost")

    assert [(a.mbid, a.disambiguation) for a in artists] == [
        ("m1", "Swedish rock band"),
        ("m2", None),
    ]


def test_expired_entries_are_dropped_on_insert():
    now = [0.0]
    client = _client(
        lambda request: httpx.Response(200, json={"setlist": []}),
        clock=lambda: now[0],
        cache_ttl_seconds=600,
    )
    client.artist_setlists("a")
    now[0] = 601
    client.artist_setlists("b")

    assert list(client._responses) == ["/artist/b/setlists?p=1"]
