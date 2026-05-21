from topsongs import missing_cli
from topsongs.models import (
    Discography,
    DiscographyAlbum,
    JellyfinArtist,
    JellyfinTrack,
    JellyfinUser,
    JellyfinUserPolicy,
)


def _user(name: str, disabled: bool = False) -> JellyfinUser:
    return JellyfinUser(id=name, name=name, policy=JellyfinUserPolicy(is_disabled=disabled))


class _SettingsBase:
    user_allowlist: list[str] = []
    user_denylist: list[str] = []
    artist_allowlist: list[str] = []
    artist_denylist: list[str] = []


class _ClientCM:
    """Context-manager protocol so stubs work with missing_cli's `with` blocks."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_select_user_by_name() -> None:
    users = [_user("Alice"), _user("Bob")]
    assert missing_cli._select_user(users, _SettingsBase(), "bob").name == "Bob"


def test_select_user_skips_disabled_when_auto_picking() -> None:
    users = [_user("Alice", disabled=True), _user("Bob")]
    assert missing_cli._select_user(users, _SettingsBase(), None).name == "Bob"


def test_select_user_requested_but_disabled_returns_none() -> None:
    users = [_user("Alice", disabled=True)]
    assert missing_cli._select_user(users, _SettingsBase(), "alice") is None


def test_select_artists_by_name() -> None:
    artists = [JellyfinArtist(id="1", name="Metallica"), JellyfinArtist(id="2", name="Slayer")]
    result = missing_cli._select_artists(artists, _SettingsBase(), "metallica")
    assert [a.name for a in result] == ["Metallica"]


def test_select_artists_all_applies_denylist() -> None:
    class Settings(_SettingsBase):
        artist_denylist = ["Slayer"]

    artists = [JellyfinArtist(id="1", name="Metallica"), JellyfinArtist(id="2", name="Slayer")]
    result = missing_cli._select_artists(artists, Settings(), None)
    assert [a.name for a in result] == ["Metallica"]


class _SettingsStub(_SettingsBase):
    jellyfin_url = "http://jellyfin:8096"
    jellyfin_api_key = "jellyfin-key"
    lastfm_api_key = "lastfm-key"
    request_timeout_seconds = 20
    request_max_retries = 2
    retry_backoff_seconds = 1.0
    log_level = "INFO"


def _wire(monkeypatch, tmp_path, jellyfin_cls, provider_cls) -> None:
    settings = type("Settings", (_SettingsStub,), {"state_dir": tmp_path})
    monkeypatch.setattr(missing_cli, "Settings", settings)
    monkeypatch.setattr(missing_cli, "JellyfinClient", jellyfin_cls)
    monkeypatch.setattr(missing_cli, "LastFmProvider", provider_cls)
    monkeypatch.setattr(missing_cli, "configure_logging", lambda level: None)


def test_main_single_artist_happy_path(monkeypatch, tmp_path, capsys) -> None:
    class JellyfinStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_users(self):
            return [_user("Alice")]

        def get_artists(self, user_id):
            return [JellyfinArtist(id="1", name="Metallica")]

        def get_tracks_for_artist(self, user_id, artist):
            return [JellyfinTrack(id="t1", name="Battery")]

    class ProviderStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_discography(self, artist_name, include_all_types=False):
            return Discography(
                artist_name=artist_name,
                albums=[
                    DiscographyAlbum(
                        title="Master of Puppets", tracks=["Battery", "Master of Puppets"]
                    )
                ],
            )

    _wire(monkeypatch, tmp_path, JellyfinStub, ProviderStub)

    assert missing_cli.main(["Metallica"]) == 0
    out = capsys.readouterr().out
    assert "Metallica" in out
    assert "Master of Puppets" in out


def test_main_artist_not_in_library_returns_nonzero(monkeypatch, tmp_path) -> None:
    class JellyfinStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_users(self):
            return [_user("Alice")]

        def get_artists(self, user_id):
            return [JellyfinArtist(id="1", name="Metallica")]

        def get_tracks_for_artist(self, user_id, artist):
            return []

    class ProviderStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_discography(self, artist_name, include_all_types=False):
            raise AssertionError("provider should not be called")

    _wire(monkeypatch, tmp_path, JellyfinStub, ProviderStub)

    assert missing_cli.main(["Nonexistent"]) == 1


def test_main_reports_provider_error_per_artist(monkeypatch, tmp_path, capsys) -> None:
    from topsongs.providers.lastfm import LastFmError

    class JellyfinStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_users(self):
            return [_user("Alice")]

        def get_artists(self, user_id):
            return [JellyfinArtist(id="1", name="Metallica")]

        def get_tracks_for_artist(self, user_id, artist):
            return []

    class ProviderStub(_ClientCM):
        def __init__(self, **kwargs) -> None:
            pass

        def get_discography(self, artist_name, include_all_types=False):
            raise LastFmError("artist=Metallica message=not found")

    _wire(monkeypatch, tmp_path, JellyfinStub, ProviderStub)

    assert missing_cli.main(["Metallica"]) == 1
    assert "Metallica" in capsys.readouterr().out
