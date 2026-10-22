import os
from types import SimpleNamespace

import pytest
from fakes import ClientCM, JellyfinStub, SetlistStub, concert, settings, user
from fastapi.testclient import TestClient

from topsongs import live
from topsongs.config import Settings
from topsongs.models import ConcertFilter, JellyfinArtist, JellyfinPlaylist, JellyfinTrack
from topsongs.web import app as webapp
from topsongs.web import services


def _client() -> TestClient:
    return TestClient(webapp.app)


# --------------------------------------------------------------------------- #
# API routing / auth
# --------------------------------------------------------------------------- #

def test_auth_open_by_default(monkeypatch):
    monkeypatch.delenv("TOPSONGS_WEB_TOKEN", raising=False)
    res = _client().get("/api/auth")
    assert res.status_code == 200
    assert res.json() == {"token_required": False, "language": "de"}


def test_token_required_blocks_and_allows(monkeypatch):
    monkeypatch.setenv("TOPSONGS_WEB_TOKEN", "s3cret")
    monkeypatch.setattr(webapp, "config_view", lambda: {"fields": []})
    client = _client()

    assert client.get("/api/config").status_code == 401
    ok = client.get("/api/config", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_status_merges_run_state(monkeypatch):
    monkeypatch.delenv("TOPSONGS_WEB_TOKEN", raising=False)
    monkeypatch.setattr(webapp, "status_payload", lambda: {"configured": True})
    monkeypatch.setattr(webapp.run_manager, "status", lambda: {"running": False})
    body = _client().get("/api/status").json()
    assert body["configured"] is True
    assert body["run"] == {"running": False}


def test_config_error_becomes_400(monkeypatch):
    monkeypatch.delenv("TOPSONGS_WEB_TOKEN", raising=False)

    def boom():
        raise services.ConfigError("kein JELLYFIN_URL")

    monkeypatch.setattr(webapp, "config_view", boom)
    res = _client().get("/api/config")
    assert res.status_code == 400
    assert "JELLYFIN_URL" in res.json()["detail"]


def test_purge_routes(monkeypatch):
    monkeypatch.delenv("TOPSONGS_WEB_TOKEN", raising=False)
    monkeypatch.setattr(webapp, "purge_preview", lambda p: {"prefix": p or "X", "playlists": []})
    monkeypatch.setattr(webapp, "purge_execute", lambda p: {"deleted": 3, "failed": 0})
    client = _client()
    preview = client.post("/api/purge/preview", json={"prefix": "Top Songs - "})
    assert preview.json()["prefix"] == "Top Songs - "
    assert client.post("/api/purge", json={}).json()["deleted"] == 3


def test_artists_route(monkeypatch):
    monkeypatch.delenv("TOPSONGS_WEB_TOKEN", raising=False)
    monkeypatch.setattr(webapp, "artist_names", lambda: {"artists": ["A", "B"], "cached": True})
    res = _client().get("/api/artists")
    assert res.status_code == 200
    assert res.json()["artists"] == ["A", "B"]


# --------------------------------------------------------------------------- #
# Services (mocked Jellyfin)
# --------------------------------------------------------------------------- #

def test_artist_names_uses_cache(tmp_path, monkeypatch):
    (tmp_path / "artists_cache.json").write_text('["Bowie", "Prince"]', encoding="utf-8")

    class Boom(ClientCM):
        def __init__(self, **kw):
            raise AssertionError("must not hit Jellyfin when the cache is warm")

    monkeypatch.setattr(services, "get_settings", lambda: settings(state_dir=tmp_path))
    monkeypatch.setattr(services, "JellyfinClient", Boom)

    out = services.artist_names()
    assert out == {"artists": ["Bowie", "Prince"], "cached": True}


def test_artist_names_cold_fetch_caches(tmp_path, monkeypatch):
    jellyfin = JellyfinStub(
        users=[user("Alice")],
        artists=[SimpleNamespace(name="Prince"), SimpleNamespace(name="Bowie")],
    )
    monkeypatch.setattr(services, "get_settings", lambda: settings(state_dir=tmp_path))
    monkeypatch.setattr(services, "JellyfinClient", jellyfin)

    out = services.artist_names()
    assert out == {"artists": ["Bowie", "Prince"], "cached": False}
    # the live fetch must have populated the on-disk cache
    assert (tmp_path / "artists_cache.json").exists()


def _aged_artist_cache(tmp_path, names: str):
    path = tmp_path / "artists_cache.json"
    path.write_text(names, encoding="utf-8")
    two_hours_ago = path.stat().st_mtime - 7200
    os.utime(path, (two_hours_ago, two_hours_ago))


def test_artist_names_refreshes_an_old_cache(tmp_path, monkeypatch):
    _aged_artist_cache(tmp_path, '["Bowie"]')
    jellyfin = JellyfinStub(
        users=[user("Alice")],
        artists=[SimpleNamespace(name="Bowie"), SimpleNamespace(name="Dark Funeral")],
    )
    monkeypatch.setattr(services, "get_settings", lambda: settings(state_dir=tmp_path))
    monkeypatch.setattr(services, "JellyfinClient", jellyfin)

    out = services.artist_names()

    assert out == {"artists": ["Bowie", "Dark Funeral"], "cached": False}


def test_artist_names_serves_an_old_cache_when_jellyfin_is_down(tmp_path, monkeypatch):
    _aged_artist_cache(tmp_path, '["Bowie"]')

    class Down(ClientCM):
        def get_users(self):
            raise ConnectionError("down")

    monkeypatch.setattr(services, "get_settings", lambda: settings(state_dir=tmp_path))
    monkeypatch.setattr(services, "JellyfinClient", Down)

    assert services.artist_names() == {"artists": ["Bowie"], "cached": True}


def test_purge_preview_and_execute(monkeypatch):
    jellyfin = JellyfinStub(
        users=[user("Alice")],
        playlists={"Alice": [JellyfinPlaylist(id="a1", name="Slayer", tags=["topsongs"])]},
    )
    monkeypatch.setattr(services, "get_settings", lambda: settings())
    monkeypatch.setattr(services, "JellyfinClient", jellyfin)

    preview = services.purge_preview(None)
    assert preview["selection"] == "Tag 'topsongs'"
    assert preview["playlists"][0]["name"] == "Slayer"

    result = services.purge_execute(None)
    assert result == {"selection": "Tag 'topsongs'", "deleted": 1, "failed": 0}
    assert jellyfin.deleted == ["a1"]


def test_purge_empty_prefix_refused(monkeypatch):
    monkeypatch.setattr(services, "get_settings", lambda: settings(playlist_name_prefix=""))
    try:
        services.purge_preview("")
    except services.ConfigError as exc:
        assert "leer" in str(exc)
    else:
        raise AssertionError("empty prefix must raise ConfigError")


def test_config_view_shows_unset_optional_value_as_dash(monkeypatch) -> None:
    settings = Settings(
        JELLYFIN_URL="http://jellyfin:8096", JELLYFIN_API_KEY="k", LASTFM_API_KEY="l"
    )
    monkeypatch.setattr(services, "get_settings", lambda: settings)
    monkeypatch.setattr(settings, "recency_bonus", None)

    fields = {field["key"]: field["value"] for field in services.config_view()["fields"]}

    assert fields["RECENCY_BONUS"] == "—"


# --------------------------------------------------------------------------- #
# Live playlists
# --------------------------------------------------------------------------- #

def _wire_live(monkeypatch, *, mbid="mb", candidates=(), playlists=()):
    concerts = [
        concert("future", [], day=30),
        concert("c2", ["Hit", "Closer"], day=12),
        concert("c1", ["Hit", "Rare"], day=5, tour="Old"),
    ]

    jellyfin = JellyfinStub(
        users=[user("alice"), user("guest")],
        artists=[JellyfinArtist(id="a", name="Band", mbid=mbid)],
        tracks=[JellyfinTrack(id="t-hit", name="Hit"), JellyfinTrack(id="t-c", name="Closer")],
        playlists=playlists,
    )

    stub_settings = settings()
    monkeypatch.setattr(services, "get_settings", lambda: stub_settings)
    monkeypatch.setattr(services, "JellyfinClient", jellyfin)
    monkeypatch.setattr(services, "_setlistfm_client", lambda s: SetlistStub(concerts, candidates))
    monkeypatch.setattr(services, "_library_cache", {})
    return jellyfin.created


def test_live_concerts_lists_newest_first_with_tours(monkeypatch):
    _wire_live(monkeypatch)

    data = services.live_concerts("band", None)

    assert data["artist"] == "Band" and data["user"] == "alice"
    assert [c["id"] for c in data["concerts"]] == ["future", "c2", "c1"]
    assert data["concerts"][0]["song_count"] == 0
    assert data["concerts"][1]["date"] == "2026-10-12"
    assert data["concerts"][1]["place"] == "Arena, Köln"
    assert data["suggestions"]["tour"] == ["Old", "Tour"]
    assert data["suggestions"]["year"] == ["2026"]


def test_live_concerts_asks_for_artist_choice(monkeypatch):
    from topsongs.models import SetlistArtist

    _wire_live(
        monkeypatch,
        mbid=None,
        candidates=[SetlistArtist(mbid="m1", name="Band"), SetlistArtist(mbid="m2", name="Band")],
    )

    data = services.live_concerts("Band", None)

    assert data["needs_choice"] is True
    assert [c["mbid"] for c in data["candidates"]] == ["m1", "m2"]


def test_live_preview_orders_by_play_count_and_suggests_name(monkeypatch):
    _wire_live(monkeypatch)

    data = services.live_preview("Band", "guest", ["c2", "c1"], 0.5)

    assert data["user"] == "guest"
    assert [(s["title"], s["play_count"], s["in_library"]) for s in data["songs"]] == [
        ("Hit", 2, True),
        ("Closer", 1, True),
        ("Rare", 1, False),
    ]
    assert data["matched_count"] == 2
    assert data["suggested_name"].startswith("Live - Band - Mix aus 2 Konzerten")


def test_live_preview_rejects_concert_without_setlist(monkeypatch):
    _wire_live(monkeypatch)

    with pytest.raises(live.LiveError):
        services.live_preview("Band", None, ["future"], 0.5)


def test_live_create_never_overwrites(monkeypatch):
    created = _wire_live(monkeypatch, playlists=[JellyfinPlaylist(id="x", name="Live - Mine")])

    data = services.live_create("Band", [], ["c2"], 0.5, "Live - Mine")

    assert [c["name"] for c in data["created"]] == ["Live - Mine (2)"]
    assert created == [("alice", "Live - Mine (2)", ["t-hit", "t-c"])]


def test_live_create_makes_a_private_copy_per_user(monkeypatch):
    created = _wire_live(monkeypatch)

    data = services.live_create("Band", ["guest", "alice", "guest"], ["c2"], 0.5, "Live - Mix")

    assert [c["user"] for c in data["created"]] == ["guest", "alice"]
    assert [entry[0] for entry in created] == ["guest", "alice"]
    assert services.JellyfinClient.public == [False, False]
    assert data["failed"] == [] and data["public"] is False


def test_live_create_public_makes_one_playlist_for_the_first_user(monkeypatch):
    created = _wire_live(monkeypatch)

    data = services.live_create("Band", ["guest", "alice"], ["c2"], 0.5, "Live - Mix", public=True)

    assert [c["user"] for c in data["created"]] == ["guest"]
    assert [entry[0] for entry in created] == ["guest"]
    assert services.JellyfinClient.public == [True]


def test_live_create_reports_the_users_it_failed_for(monkeypatch):
    _wire_live(monkeypatch)

    data = services.live_create("Band", ["alice", "ghost"], ["c2"], 0.5, "Live - Mix")

    assert [c["user"] for c in data["created"]] == ["alice"]
    assert data["failed"] == [
        {"user": "ghost", "error": "Benutzer 'ghost' nicht gefunden oder deaktiviert."}
    ]


def test_live_create_fails_when_no_playlist_was_created(monkeypatch):
    _wire_live(monkeypatch)

    with pytest.raises(live.LiveError, match="ghost"):
        services.live_create("Band", ["ghost"], ["c2"], 0.5, "Live - Mix")


def test_live_playlist_route_passes_users_and_public(monkeypatch):
    monkeypatch.delenv("TOPSONGS_WEB_TOKEN", raising=False)
    calls = []
    monkeypatch.setattr(webapp, "live_create", lambda *args: calls.append(args) or {"ok": 1})

    res = _client().post(
        "/api/live/playlist",
        json={"artist": "Band", "users": ["a", "b"], "public": True, "setlist_ids": ["c2"],
              "name": "Live - X"},
    )

    assert res.status_code == 200
    assert calls == [("Band", ["a", "b"], ["c2"], 0.5, "Live - X", True)]


def test_live_playlists_lists_only_tagged_ones(monkeypatch):
    _wire_live(
        monkeypatch,
        playlists=[
            JellyfinPlaylist(id="1", name="Live - Band - Arena", tags=["topsongs-live"]),
            JellyfinPlaylist(id="2", name="Live - selbst gemacht"),
        ],
    )

    data = services.live_playlists()

    assert data == {"playlists": [{"name": "Live - Band - Arena", "users": ["alice", "guest"]}]}


def test_prune_preview_shows_live_playlists_as_protected(monkeypatch):
    _wire_live(
        monkeypatch,
        playlists=[
            JellyfinPlaylist(id="1", name="Live - Band - Arena", tags=["topsongs-live"]),
            JellyfinPlaylist(id="2", name="Junk"),
        ],
    )

    data = services.prune_preview(["Favorites"], "")

    assert [p["name"] for p in data["protected"]] == ["Live - Band - Arena"]
    assert [p["name"] for p in data["delete"]] == ["Junk"]


def test_live_errors_become_400(monkeypatch):
    monkeypatch.delenv("TOPSONGS_WEB_TOKEN", raising=False)

    def boom(*args):
        raise live.LiveError("'X' ist nicht in der Bibliothek von alice.")

    monkeypatch.setattr(webapp, "live_preview", boom)
    res = _client().post(
        "/api/live/preview", json={"artist": "X", "setlist_ids": ["a"], "min_share": 0.5}
    )

    assert res.status_code == 400
    assert "Bibliothek" in res.json()["detail"]


def test_users_route_filters_disabled_and_denied(monkeypatch):
    _wire_live(monkeypatch)
    monkeypatch.setattr(
        services, "get_settings", lambda: settings(user_denylist=["guest"])
    )

    assert services.user_names() == {"users": ["alice"], "default": "alice"}


def test_live_previews_reuse_the_library_lookup(monkeypatch):
    _wire_live(monkeypatch)
    calls = []
    original = services.live.find_library_artist
    monkeypatch.setattr(
        services.live,
        "find_library_artist",
        lambda *a: calls.append(1) or original(*a),
    )

    services.live_concerts("Band", "alice")
    services.live_preview("Band", "alice", ["c2"], 0.5)
    services.live_preview("Band", "alice", ["c2", "c1"], 0.5)

    assert len(calls) == 1


def test_live_concerts_suggestions_keep_the_unfiltered_values(monkeypatch):
    _wire_live(monkeypatch)

    data = services.live_concerts("Band", None, None, ConcertFilter(tour="Old"))

    assert [c["id"] for c in data["concerts"]] == ["c1"]
    assert data["suggestions"]["tour"] == ["Old", "Tour"]


def test_live_concerts_route_reads_the_filter_from_the_query(monkeypatch):
    monkeypatch.delenv("TOPSONGS_WEB_TOKEN", raising=False)
    seen = []
    monkeypatch.setattr(
        webapp, "live_concerts", lambda *args: seen.append(args) or {"concerts": []}
    )

    ok = _client().get("/api/live/concerts?artist=Band&tour=M72&year=2026&city=+&country=de")
    bad = _client().get("/api/live/concerts?artist=Band&year=abc")

    assert ok.status_code == 200 and bad.status_code == 422
    assert seen == [("Band", None, None, ConcertFilter(tour="M72", year=2026, country="de"))]
