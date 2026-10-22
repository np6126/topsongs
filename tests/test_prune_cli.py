from fakes import JellyfinStub, user, wire_cli

from topsongs import prune_cli
from topsongs.models import JellyfinPlaylist


def test_prune_keeps_named_and_deletes_rest_for_all_users(monkeypatch, tmp_path) -> None:
    users = [user("Alice"), user("Bob")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Favorites"),
            JellyfinPlaylist(id="a2", name="Metallica"),
        ],
        "Bob": [JellyfinPlaylist(id="b1", name="Slayer")],
    }
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)

    assert prune_cli.main(["--keep", "Favorites", "--yes"]) == 0
    assert sorted(jellyfin.deleted) == ["a2", "b1"]


def test_prune_renames_keepers_with_prefix(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Favorites"),
            JellyfinPlaylist(id="a2", name="Roadtrip"),
            JellyfinPlaylist(id="a3", name="Metallica"),
        ]
    }
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)

    rc = prune_cli.main(["--keep", "Favorites,Roadtrip", "--rename-prefix", "_", "--yes"])
    assert rc == 0
    assert jellyfin.deleted == ["a3"]
    assert sorted(jellyfin.renamed) == [("a1", "_Favorites"), ("a2", "_Roadtrip")]


def test_prune_is_idempotent_for_already_prefixed_keepers(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="_Favorites"),
            JellyfinPlaylist(id="a2", name="Metallica"),
        ]
    }
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)

    rc = prune_cli.main(["--keep", "Favorites", "--rename-prefix", "_", "--yes"])
    assert rc == 0
    assert jellyfin.deleted == ["a2"]  # _Favorites kept, not deleted
    assert jellyfin.renamed == []  # already prefixed, not renamed again


def test_prune_dedupes_shared_playlist_by_id(monkeypatch, tmp_path) -> None:
    users = [user("Alice"), user("Bob")]
    shared = JellyfinPlaylist(id="shared", name="Tool")
    playlists = {"Alice": [shared], "Bob": [shared]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)

    assert prune_cli.main(["--keep", "Favorites", "--yes"]) == 0
    assert jellyfin.deleted == ["shared"]


def test_prune_dry_run_changes_nothing(monkeypatch, tmp_path, capsys) -> None:
    users = [user("Alice")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Favorites"),
            JellyfinPlaylist(id="a2", name="Metallica"),
        ]
    }
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)

    rc = prune_cli.main(["--keep", "Favorites", "--rename-prefix", "_", "--dry-run"])
    assert rc == 0
    assert jellyfin.deleted == []
    assert jellyfin.renamed == []
    assert "Dry-Run" in capsys.readouterr().out


def test_prune_requires_keep(monkeypatch, tmp_path, capsys) -> None:
    users = [user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Metallica")]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)

    assert prune_cli.main(["--yes"]) == 1
    assert jellyfin.deleted == []
    assert "ALLE Playlists" in capsys.readouterr().out


def test_prune_aborts_when_not_confirmed(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Metallica")]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)
    monkeypatch.setattr("builtins.input", lambda prompt="": "nein")

    assert prune_cli.main(["--keep", "Favorites"]) == 0
    assert jellyfin.deleted == []


def test_prune_nothing_to_do_returns_zero(monkeypatch, tmp_path, capsys) -> None:
    users = [user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="_Favorites")]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)

    rc = prune_cli.main(["--keep", "Favorites", "--rename-prefix", "_", "--yes"])
    assert rc == 0
    assert jellyfin.deleted == []
    assert "Nichts zu tun" in capsys.readouterr().out


def test_prune_reports_delete_failure_as_nonzero(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]

    jellyfin = JellyfinStub(
        users=users,
        playlists=[JellyfinPlaylist(id="a1", name="Metallica")],
        delete_error=RuntimeError("delete failed"),
    )
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)

    assert prune_cli.main(["--keep", "Favorites", "--yes"]) == 1
    assert jellyfin.renamed == []


def test_prune_warns_on_unmatched_keep_name(monkeypatch, tmp_path, capsys) -> None:
    users = [user("Alice")]
    playlists = {"Alice": [JellyfinPlaylist(id="a1", name="Metallica")]}
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)

    prune_cli.main(["--keep", "Favorites", "--dry-run"])
    assert "kein Treffer" in capsys.readouterr().out


def test_prune_never_deletes_or_renames_live_playlists(monkeypatch, tmp_path) -> None:
    users = [user("Alice")]
    playlists = {
        "Alice": [
            JellyfinPlaylist(id="a1", name="Favorites"),
            JellyfinPlaylist(
                id="a2", name="Live - Metallica - Olympiastadion", tags=["topsongs-live"]
            ),
            JellyfinPlaylist(id="a3", name="Metallica"),
        ]
    }
    jellyfin = JellyfinStub(users=users, playlists=playlists)
    wire_cli(monkeypatch, prune_cli, tmp_path, jellyfin)

    rc = prune_cli.main(["--keep", "Favorites", "--rename-prefix", "_", "--yes"])

    assert rc == 0
    assert jellyfin.deleted == ["a3"]
    assert jellyfin.renamed == [("a1", "_Favorites")]
