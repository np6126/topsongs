from fakes import JellyfinStub, user, wire_cli

from topsongs import purge_cli
from topsongs.models import JellyfinPlaylist

NIGHTLY = ["topsongs"]


def test_purge_deletes_only_tagged_playlists_for_all_users(monkeypatch, tmp_path) -> None:
    users = [user("Alice"), user("Bob")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Top Songs - Metallica", tags=NIGHTLY),
            JellyfinPlaylist(id="a2", name="My Mixtape"),
        ],
        "Bob": [JellyfinPlaylist(id="b1", name="Top Songs - Slayer", tags=NIGHTLY)],
    }
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--yes"]) == 0
    assert sorted(jellyfin.deleted) == ["a1", "b1"]


def test_purge_deduplicates_shared_playlist_by_id(monkeypatch, tmp_path) -> None:
    users = [user("Alice"), user("Bob")]
    shared = JellyfinPlaylist(id="shared", name="Top Songs - Tool", tags=NIGHTLY)
    playlists = {"Alice": [shared], "Bob": [shared]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--yes"]) == 0
    assert jellyfin.deleted == ["shared"]


def test_purge_dry_run_deletes_nothing(monkeypatch, tmp_path, capsys) -> None:
    users = [user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Metallica", tags=NIGHTLY)]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--dry-run"]) == 0
    assert jellyfin.deleted == []
    assert "Dry-Run" in capsys.readouterr().out


def test_purge_settings_dry_run_deletes_nothing(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Metallica", tags=NIGHTLY)]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin, dry_run=True)

    assert purge_cli.main(["--yes"]) == 0
    assert jellyfin.deleted == []


def test_purge_aborts_when_not_confirmed(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Metallica", tags=NIGHTLY)]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)
    monkeypatch.setattr("builtins.input", lambda prompt="": "nein")

    assert purge_cli.main([]) == 0
    assert jellyfin.deleted == []


def test_purge_confirmed_interactively_deletes(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Metallica", tags=NIGHTLY)]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)
    monkeypatch.setattr("builtins.input", lambda prompt="": "ja")

    assert purge_cli.main([]) == 0
    assert jellyfin.deleted == ["a1"]


def test_purge_no_matches_returns_zero(monkeypatch, tmp_path, capsys) -> None:
    users = [user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="My Mixtape")]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--yes"]) == 0
    assert jellyfin.deleted == []
    assert "Keine Playlists" in capsys.readouterr().out


def test_purge_prefix_argument_overrides_settings(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Top Songs - Metallica", tags=NIGHTLY),
            JellyfinPlaylist(id="a2", name="Mix - Slayer"),
        ]
    }
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--yes", "--prefix", "Mix - "]) == 0
    assert jellyfin.deleted == ["a2"]


def test_purge_explicit_empty_prefix_refuses(monkeypatch, tmp_path, capsys) -> None:
    users = [user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Top Songs - Metallica", tags=NIGHTLY)]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--yes", "--prefix", ""]) == 1
    assert jellyfin.deleted == []
    assert "leer" in capsys.readouterr().out


def test_purge_skips_user_whose_playlists_fail_to_load(monkeypatch, tmp_path) -> None:
    users = [user("Alice"), user("Bob")]

    class AliceFails(JellyfinStub):
        def get_playlists_for_user(self, user_id, media_types="Audio"):
            if user_id == "Alice":
                raise RuntimeError("boom")
            return super().get_playlists_for_user(user_id, media_types)

    slayer = JellyfinPlaylist(id="b1", name="Top Songs - Slayer", tags=NIGHTLY)
    jellyfin = AliceFails(users=users, playlists={"Bob": [slayer]})
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--yes"]) == 0
    assert jellyfin.deleted == ["b1"]


def test_purge_reports_delete_failure_as_nonzero(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]

    jellyfin = JellyfinStub(
        users=users,
        playlists=[JellyfinPlaylist(id="a1", name="Top Songs - Metallica", tags=NIGHTLY)],
        delete_error=RuntimeError("delete failed"),
    )
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--yes"]) == 1


def test_purge_goes_by_the_tag_not_the_name(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]
    playlists = [
        JellyfinPlaylist(id="nightly", name="AC_DC", tags=["topsongs"]),
        JellyfinPlaylist(id="own", name="Top Songs - selbst gemacht"),
        JellyfinPlaylist(id="live", name="Live - AC_DC", tags=["topsongs-live"]),
    ]
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--yes"]) == 0
    assert jellyfin.deleted == ["nightly"]


def test_purge_by_prefix_never_deletes_live_playlists(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]
    playlists = [
        JellyfinPlaylist(id="old", name="Live Mitschnitt"),
        JellyfinPlaylist(id="live", name="Live - AC_DC", tags=["topsongs-live"]),
    ]
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--prefix", "Live", "--yes"]) == 0
    assert jellyfin.deleted == ["old"]
