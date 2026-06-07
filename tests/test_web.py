from types import SimpleNamespace

from fastapi.testclient import TestClient

from topsongs.models import JellyfinPlaylist, JellyfinUser, JellyfinUserPolicy
from topsongs.web import app as webapp
from topsongs.web import services


def _client() -> TestClient:
    return TestClient(webapp.app)


def _user(name: str) -> JellyfinUser:
    return JellyfinUser(id=name, name=name, policy=JellyfinUserPolicy())


def _settings(**over):
    base = dict(
        jellyfin_url="http://jellyfin:8096",
        jellyfin_api_key="k",
        lastfm_api_key="l",
        request_timeout_seconds=20,
        request_max_retries=2,
        retry_backoff_seconds=1.0,
        playlist_tag_managed=False,
        playlist_managed_tag="topsongs",
        playlist_name_prefix="Top Songs - ",
    )
    base.update(over)
    return SimpleNamespace(**base)


class _ClientCM:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --------------------------------------------------------------------------- #
# API routing / auth
# --------------------------------------------------------------------------- #

def test_auth_open_by_default(monkeypatch):
    monkeypatch.delenv("TOPSONGS_WEB_TOKEN", raising=False)
    res = _client().get("/api/auth")
    assert res.status_code == 200
    assert res.json() == {"token_required": False}


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

    class Boom(_ClientCM):
        def __init__(self, **kw):
            raise AssertionError("must not hit Jellyfin when the cache is warm")

    monkeypatch.setattr(services, "get_settings", lambda: _settings(state_dir=tmp_path))
    monkeypatch.setattr(services, "JellyfinClient", Boom)

    out = services.artist_names()
    assert out == {"artists": ["Bowie", "Prince"], "cached": True}


def test_artist_names_cold_fetch_caches(tmp_path, monkeypatch):
    class Stub(_ClientCM):
        def __init__(self, **kw):
            pass

        def close(self):
            pass

        def get_users(self):
            return [_user("Alice")]

        def get_artists(self, uid):
            return [SimpleNamespace(name="Prince"), SimpleNamespace(name="Bowie")]

    monkeypatch.setattr(
        services,
        "get_settings",
        lambda: _settings(state_dir=tmp_path, user_allowlist=[], user_denylist=[]),
    )
    monkeypatch.setattr(services, "JellyfinClient", Stub)

    out = services.artist_names()
    assert out == {"artists": ["Bowie", "Prince"], "cached": False}
    # the live fetch must have populated the on-disk cache
    assert (tmp_path / "artists_cache.json").exists()


def test_purge_preview_and_execute(monkeypatch):
    deleted = []
    pls = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Slayer")]}

    class Stub(_ClientCM):
        def __init__(self, **kw):
            pass

        def close(self):
            pass

        def get_users(self):
            return [_user("Alice")]

        def get_playlists_for_user(self, uid, media_types="Audio"):
            return pls.get(uid, [])

        def delete_playlist(self, pid):
            deleted.append(pid)

    monkeypatch.setattr(services, "get_settings", lambda: _settings())
    monkeypatch.setattr(services, "JellyfinClient", Stub)

    preview = services.purge_preview(None)
    assert preview["prefix"] == "Top Songs - "
    assert preview["playlists"][0]["name"] == "Top Songs - Slayer"

    result = services.purge_execute(None)
    assert result == {"prefix": "Top Songs - ", "deleted": 1, "failed": 0}
    assert deleted == ["a1"]


def test_purge_empty_prefix_refused(monkeypatch):
    monkeypatch.setattr(services, "get_settings", lambda: _settings(playlist_name_prefix=""))
    try:
        services.purge_preview("")
    except services.ConfigError as exc:
        assert "leer" in str(exc)
    else:
        raise AssertionError("empty prefix must raise ConfigError")
