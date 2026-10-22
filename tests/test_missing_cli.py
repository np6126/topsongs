from fakes import ClientCM, JellyfinStub, settings, user, wire_cli

from topsongs import missing_cli
from topsongs.models import (
    Discography,
    DiscographyAlbum,
    JellyfinArtist,
    JellyfinTrack,
)


def test_select_user_by_name() -> None:
    users = [user("Alice"), user("Bob")]
    assert missing_cli._select_user(users, settings(), "bob").name == "Bob"


def test_select_user_skips_disabled_when_auto_picking() -> None:
    users = [user("Alice", disabled=True), user("Bob")]
    assert missing_cli._select_user(users, settings(), None).name == "Bob"


def test_select_user_requested_but_disabled_returns_none() -> None:
    users = [user("Alice", disabled=True)]
    assert missing_cli._select_user(users, settings(), "alice") is None


def test_select_artists_by_name() -> None:
    artists = [JellyfinArtist(id="1", name="Metallica"), JellyfinArtist(id="2", name="Slayer")]
    result = missing_cli._select_artists(artists, settings(), "metallica")
    assert [a.name for a in result] == ["Metallica"]


def test_select_artists_all_applies_denylist() -> None:
    artists = [JellyfinArtist(id="1", name="Metallica"), JellyfinArtist(id="2", name="Slayer")]
    result = missing_cli._select_artists(artists, settings(artist_denylist=["Slayer"]), None)
    assert [a.name for a in result] == ["Metallica"]


def _wire(monkeypatch, tmp_path, provider_cls, tracks=()) -> None:
    jellyfin = JellyfinStub(
        users=[user("Alice")], artists=[JellyfinArtist(id="1", name="Metallica")], tracks=tracks
    )
    wire_cli(monkeypatch, missing_cli, tmp_path, jellyfin)
    monkeypatch.setattr(missing_cli, "LastFmProvider", provider_cls)


def test_main_single_artist_happy_path(monkeypatch, tmp_path, capsys) -> None:
    class ProviderStub(ClientCM):
        def get_discography(self, artist_name, include_all_types=False):
            return Discography(
                artist_name=artist_name,
                albums=[
                    DiscographyAlbum(
                        title="Master of Puppets", tracks=["Battery", "Master of Puppets"]
                    )
                ],
            )

    _wire(monkeypatch, tmp_path, ProviderStub, [JellyfinTrack(id="t1", name="Battery")])

    assert missing_cli.main(["Metallica"]) == 0
    out = capsys.readouterr().out
    assert "Metallica" in out
    assert "Master of Puppets" in out


def test_main_artist_not_in_library_returns_nonzero(monkeypatch, tmp_path) -> None:
    class ProviderStub(ClientCM):
        def get_discography(self, artist_name, include_all_types=False):
            raise AssertionError("provider should not be called")

    _wire(monkeypatch, tmp_path, ProviderStub)

    assert missing_cli.main(["Nonexistent"]) == 1


def test_main_reports_provider_error_per_artist(monkeypatch, tmp_path, capsys) -> None:
    from topsongs.providers.lastfm import LastFmError

    class ProviderStub(ClientCM):
        def get_discography(self, artist_name, include_all_types=False):
            raise LastFmError("artist=Metallica message=not found")

    _wire(monkeypatch, tmp_path, ProviderStub)

    assert missing_cli.main(["Metallica"]) == 1
    assert "Metallica" in capsys.readouterr().out
