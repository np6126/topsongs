import pytest

from topsongs.providers.lastfm import (
    LastFmError,
    LastFmProvider,
    _album_base_key,
    _clean_display_title,
    _is_studio_album,
)


def test_is_studio_album_keeps_studio_and_eps() -> None:
    assert _is_studio_album("Master of Puppets")
    assert _is_studio_album("Garage Days Re-Revisited")
    assert _is_studio_album("Reload")


def test_is_studio_album_rejects_non_studio() -> None:
    assert not _is_studio_album("Greatest Hits")
    assert not _is_studio_album("The Best of Metallica")
    assert not _is_studio_album("Live at Wembley")
    assert not _is_studio_album("MTV Unplugged")
    assert not _is_studio_album("B-Sides and Rarities")


def test_album_base_key_collapses_editions() -> None:
    base = _album_base_key("Master of Puppets")
    assert _album_base_key("Master of Puppets (Deluxe Edition)") == base
    assert _album_base_key("Master of Puppets (Remastered 2017)") == base
    assert _album_base_key("Master of Puppets - Remastered") == base


def test_clean_display_title_strips_edition_suffixes() -> None:
    assert _clean_display_title("Master of Puppets (Remastered)") == "Master of Puppets"
    assert _clean_display_title("Ride the Lightning") == "Ride the Lightning"


def _fake_request(payloads: dict):
    def request(params, artist_name):
        method = params["method"]
        if method == "artist.gettopalbums":
            return payloads["topalbums"]
        if method == "album.getinfo":
            empty = {"album": {"tracks": {"track": []}}}
            return payloads["getinfo"].get(params.get("album"), empty)
        raise AssertionError(f"unexpected method {method}")

    return request


def test_get_discography_dedups_filters_and_fetches_tracks(monkeypatch) -> None:
    provider = LastFmProvider(api_key="k")
    payloads = {
        "topalbums": {
            "topalbums": {
                "album": [
                    {"name": "Master of Puppets", "playcount": "100", "mbid": ""},
                    {"name": "Master of Puppets (Remastered)", "playcount": "50", "mbid": ""},
                    {"name": "Greatest Hits", "playcount": "200", "mbid": ""},
                    {"name": "Ride the Lightning", "playcount": "80", "mbid": ""},
                ]
            }
        },
        "getinfo": {
            "Master of Puppets": {
                "album": {
                    "tracks": {
                        "track": [
                            {"name": "Battery"},
                            {"name": "Master of Puppets"},
                            {"name": "The Thing That Should Not Be"},
                        ]
                    }
                }
            },
            "Ride the Lightning": {
                "album": {
                    "tracks": {
                        "track": [
                            {"name": "Fight Fire with Fire"},
                            {"name": "Ride the Lightning"},
                            {"name": "For Whom the Bell Tolls"},
                        ]
                    }
                }
            },
        },
    }
    monkeypatch.setattr(provider, "_request_json", _fake_request(payloads))

    disco = provider.get_discography("Metallica")

    titles = {album.title for album in disco.albums}
    assert titles == {"Master of Puppets", "Ride the Lightning"}
    mop = next(a for a in disco.albums if a.title == "Master of Puppets")
    assert mop.tracks == ["Battery", "Master of Puppets", "The Thing That Should Not Be"]


def test_get_discography_keeps_singles(monkeypatch) -> None:
    """A 1-track single is a real release and is kept in the default scope."""
    provider = LastFmProvider(api_key="k")
    payloads = {
        "topalbums": {
            "topalbums": {
                "album": [
                    {"name": "Real Album", "playcount": "100", "mbid": ""},
                    {"name": "Just a Single", "playcount": "90", "mbid": ""},
                ]
            }
        },
        "getinfo": {
            "Real Album": {
                "album": {
                    "tracks": {"track": [{"name": "One"}, {"name": "Two"}, {"name": "Three"}]}
                }
            },
            "Just a Single": {"album": {"tracks": {"track": [{"name": "Just a Single"}]}}},
        },
    }
    monkeypatch.setattr(provider, "_request_json", _fake_request(payloads))

    disco = provider.get_discography("X")

    assert {album.title for album in disco.albums} == {"Real Album", "Just a Single"}


def test_get_discography_includes_compilations_with_all_types(monkeypatch) -> None:
    provider = LastFmProvider(api_key="k")
    payloads = {
        "topalbums": {
            "topalbums": {"album": [{"name": "Greatest Hits", "playcount": "10", "mbid": ""}]}
        },
        "getinfo": {"Greatest Hits": {"album": {"tracks": {"track": [{"name": "One"}]}}}},
    }
    monkeypatch.setattr(provider, "_request_json", _fake_request(payloads))

    disco = provider.get_discography("X", include_all_types=True)

    assert [album.title for album in disco.albums] == ["Greatest Hits"]


def test_get_discography_skips_albums_without_tracklists(monkeypatch) -> None:
    provider = LastFmProvider(api_key="k")
    payloads = {
        "topalbums": {
            "topalbums": {"album": [{"name": "Mystery Album", "playcount": "5", "mbid": ""}]}
        },
        "getinfo": {},
    }
    monkeypatch.setattr(provider, "_request_json", _fake_request(payloads))

    disco = provider.get_discography("X")

    assert disco.albums == []


def test_get_discography_raises_on_lastfm_error(monkeypatch) -> None:
    provider = LastFmProvider(api_key="k")
    monkeypatch.setattr(
        provider, "_request_json", lambda params, artist: {"error": 6, "message": "not found"}
    )

    with pytest.raises(LastFmError):
        provider.get_discography("Nonexistent")
