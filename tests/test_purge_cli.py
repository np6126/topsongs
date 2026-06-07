from topsongs import purge_cli
from topsongs.models import JellyfinPlaylist, JellyfinUser, JellyfinUserPolicy


def _user(name: str) -> JellyfinUser:
    return JellyfinUser(id=name, name=name, policy=JellyfinUserPolicy())


class _ClientCM:
    """Context-manager protocol so stubs work with purge_cli's `with` block."""

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
    playlist_name_prefix = "Top Songs - "
    dry_run = False


def _wire(monkeypatch, tmp_path, jellyfin_cls, settings_overrides=None) -> None:
    settings = type(
        "Settings", (_SettingsStub,), {"state_dir": tmp_path, **(settings_overrides or {})}
    )
    monkeypatch.setattr(purge_cli, "Settings", settings)
    monkeypatch.setattr(purge_cli, "JellyfinClient", jellyfin_cls)
    monkeypatch.setattr(purge_cli, "configure_logging", lambda level: None)


def _stub(users, playlists_by_user, deleted_sink):
    class JellyfinStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_users(self):
            return users

        def get_playlists_for_user(self, user_id):
            return playlists_by_user.get(user_id, [])

        def delete_playlist(self, playlist_id):
            deleted_sink.append(playlist_id)

    return JellyfinStub


def test_purge_deletes_only_prefixed_playlists_for_all_users(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    users = [_user("Alice"), _user("Bob")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Top Songs - Metallica"),
            JellyfinPlaylist(id="a2", name="My Mixtape"),
        ],
        "Bob": [JellyfinPlaylist(id="b1", name="Top Songs - Slayer")],
    }
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))

    assert purge_cli.main(["--yes"]) == 0
    assert sorted(deleted) == ["a1", "b1"]


def test_purge_deduplicates_shared_playlist_by_id(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    users = [_user("Alice"), _user("Bob")]
    shared = JellyfinPlaylist(id="shared", name="Top Songs - Tool")
    playlists = {"Alice": [shared], "Bob": [shared]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))

    assert purge_cli.main(["--yes"]) == 0
    assert deleted == ["shared"]


def test_purge_dry_run_deletes_nothing(monkeypatch, tmp_path, capsys) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Metallica")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))

    assert purge_cli.main(["--dry-run"]) == 0
    assert deleted == []
    assert "Dry-Run" in capsys.readouterr().out


def test_purge_settings_dry_run_deletes_nothing(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Metallica")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted), {"dry_run": True})

    assert purge_cli.main(["--yes"]) == 0
    assert deleted == []


def test_purge_aborts_when_not_confirmed(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Metallica")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))
    monkeypatch.setattr("builtins.input", lambda prompt="": "nein")

    assert purge_cli.main([]) == 0
    assert deleted == []


def test_purge_confirmed_interactively_deletes(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Metallica")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))
    monkeypatch.setattr("builtins.input", lambda prompt="": "ja")

    assert purge_cli.main([]) == 0
    assert deleted == ["a1"]


def test_purge_no_matches_returns_zero(monkeypatch, tmp_path, capsys) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="My Mixtape")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))

    assert purge_cli.main(["--yes"]) == 0
    assert deleted == []
    assert "Keine Playlists" in capsys.readouterr().out


def test_purge_empty_prefix_refuses(monkeypatch, tmp_path, capsys) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Anything")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted), {"playlist_name_prefix": ""})

    assert purge_cli.main(["--yes"]) == 1
    assert deleted == []
    assert "leer" in capsys.readouterr().out


def test_purge_prefix_argument_overrides_settings(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Top Songs - Metallica"),
            JellyfinPlaylist(id="a2", name="Mix - Slayer"),
        ]
    }
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))

    assert purge_cli.main(["--yes", "--prefix", "Mix - "]) == 0
    assert deleted == ["a2"]


def test_purge_explicit_empty_prefix_refuses(monkeypatch, tmp_path, capsys) -> None:
    deleted: list[str] = []
    users = [_user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Metallica")]}
    _wire(monkeypatch, tmp_path, _stub(users, playlists, deleted))

    assert purge_cli.main(["--yes", "--prefix", ""]) == 1
    assert deleted == []
    assert "leer" in capsys.readouterr().out


def test_purge_skips_user_whose_playlists_fail_to_load(monkeypatch, tmp_path) -> None:
    deleted: list[str] = []
    users = [_user("Alice"), _user("Bob")]

    class JellyfinStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_users(self):
            return users

        def get_playlists_for_user(self, user_id):
            if user_id == "Alice":
                raise RuntimeError("boom")
            return [JellyfinPlaylist(id="b1", name="Top Songs - Slayer")]

        def delete_playlist(self, playlist_id):
            deleted.append(playlist_id)

    _wire(monkeypatch, tmp_path, JellyfinStub)

    assert purge_cli.main(["--yes"]) == 0
    assert deleted == ["b1"]


def test_purge_reports_delete_failure_as_nonzero(monkeypatch, tmp_path) -> None:
    users = [_user("Alice")]

    class JellyfinStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_users(self):
            return users

        def get_playlists_for_user(self, user_id):
            return [JellyfinPlaylist(id="a1", name="Top Songs - Metallica")]

        def delete_playlist(self, playlist_id):
            raise RuntimeError("delete failed")

    _wire(monkeypatch, tmp_path, JellyfinStub)

    assert purge_cli.main(["--yes"]) == 1
