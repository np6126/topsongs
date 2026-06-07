from topsongs import prune_cli
from topsongs.models import JellyfinPlaylist, JellyfinUser, JellyfinUserPolicy


def _user(name: str) -> JellyfinUser:
    return JellyfinUser(id=name, name=name, policy=JellyfinUserPolicy())


class _ClientCM:
    """Context-manager protocol so stubs work with prune_cli's `with` block."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _SettingsStub:
    jellyfin_url = "http://jellyfin:8096"
    jellyfin_api_key = "jellyfin-key"
    request_timeout_seconds = 20
    request_max_retries = 2
    retry_backoff_seconds = 1.0
    log_level = "INFO"
    dry_run = False


def _wire(monkeypatch, tmp_path, jellyfin_cls, settings_overrides=None) -> None:
    settings = type(
        "Settings", (_SettingsStub,), {"state_dir": tmp_path, **(settings_overrides or {})}
    )
    monkeypatch.setattr(prune_cli, "Settings", settings)
    monkeypatch.setattr(prune_cli, "JellyfinClient", jellyfin_cls)
    monkeypatch.setattr(prune_cli, "configure_logging", lambda level: None)


def _stub(users, playlists_by_user, deleted_sink, renamed_sink=None):
    class JellyfinStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_users(self):
            return users

        def get_playlists_for_user(self, user_id, media_types="Audio"):
            return playlists_by_user.get(user_id, [])

        def delete_playlist(self, playlist_id):
            deleted_sink.append(playlist_id)

        def rename_playlist(self, user_id, playlist_id, new_name):
            if renamed_sink is not None:
                renamed_sink.append((playlist_id, new_name))

    return JellyfinStub


def test_prune_keeps_named_and_deletes_rest_for_all_users(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    users = [_user("Alice"), _user("Bob")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Favorites"),
            JellyfinPlaylist(id="a2", name="Metallica"),
        ],
        "Bob": [JellyfinPlaylist(id="b1", name="Slayer")],
    }
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))

    assert prune_cli.main(["--keep", "Favorites", "--yes"]) == 0
    assert sorted(deleted) == ["a2", "b1"]


def test_prune_renames_keepers_with_prefix(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    renamed: list[tuple[str, str]] = []
    users = [_user("Alice")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Favorites"),
            JellyfinPlaylist(id="a2", name="Roadtrip"),
            JellyfinPlaylist(id="a3", name="Metallica"),
        ]
    }
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted, renamed))

    rc = prune_cli.main(["--keep", "Favorites,Roadtrip", "--rename-prefix", "_", "--yes"])
    assert rc == 0
    assert deleted == ["a3"]
    assert sorted(renamed) == [("a1", "_Favorites"), ("a2", "_Roadtrip")]


def test_prune_is_idempotent_for_already_prefixed_keepers(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    renamed: list[tuple[str, str]] = []
    users = [_user("Alice")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="_Favorites"),
            JellyfinPlaylist(id="a2", name="Metallica"),
        ]
    }
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted, renamed))

    rc = prune_cli.main(["--keep", "Favorites", "--rename-prefix", "_", "--yes"])
    assert rc == 0
    assert deleted == ["a2"]  # _Favorites kept, not deleted
    assert renamed == []  # already prefixed, not renamed again


def test_prune_dedupes_shared_playlist_by_id(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    users = [_user("Alice"), _user("Bob")]
    shared = JellyfinPlaylist(id="shared", name="Tool")
    playlists = {"Alice": [shared], "Bob": [shared]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))

    assert prune_cli.main(["--keep", "Favorites", "--yes"]) == 0
    assert deleted == ["shared"]


def test_prune_dry_run_changes_nothing(monkeypatch, tmp_path, capsys) -> None:
    deleted: list[str] = []
    renamed: list[tuple[str, str]] = []
    users = [_user("Alice")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Favorites"),
            JellyfinPlaylist(id="a2", name="Metallica"),
        ]
    }
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted, renamed))

    rc = prune_cli.main(["--keep", "Favorites", "--rename-prefix", "_", "--dry-run"])
    assert rc == 0
    assert deleted == []
    assert renamed == []
    assert "Dry-Run" in capsys.readouterr().out


def test_prune_requires_keep(monkeypatch, tmp_path, capsys) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Metallica")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))

    assert prune_cli.main(["--yes"]) == 1
    assert deleted == []
    assert "ALLE Playlists" in capsys.readouterr().out


def test_prune_aborts_when_not_confirmed(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Metallica")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))
    monkeypatch.setattr("builtins.input", lambda prompt="": "nein")

    assert prune_cli.main(["--keep", "Favorites"]) == 0
    assert deleted == []


def test_prune_nothing_to_do_returns_zero(monkeypatch, tmp_path, capsys) -> None:
    deleted: list[str] = []
    renamed: list[tuple[str, str]] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="_Favorites")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted, renamed))

    rc = prune_cli.main(["--keep", "Favorites", "--rename-prefix", "_", "--yes"])
    assert rc == 0
    assert deleted == []
    assert "Nichts zu tun" in capsys.readouterr().out


def test_prune_reports_delete_failure_as_nonzero(monkeypatch, tmp_path) -> None:
    users = [_user("Alice")]

    class JellyfinStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_users(self):
            return users

        def get_playlists_for_user(self, user_id, media_types="Audio"):
            return [JellyfinPlaylist(id="a1", name="Metallica")]

        def delete_playlist(self, playlist_id):
            raise RuntimeError("delete failed")

        def rename_playlist(self, user_id, playlist_id, new_name):
            raise AssertionError("should not rename")

    _wire(monkeypatch, tmp_path, JellyfinStub)

    assert prune_cli.main(["--keep", "Favorites", "--yes"]) == 1


def test_prune_warns_on_unmatched_keep_name(monkeypatch, tmp_path, capsys) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Metallica")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))

    prune_cli.main(["--keep", "Favorites", "--dry-run"])
    assert "kein Treffer" in capsys.readouterr().out
