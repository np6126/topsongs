from topsongs.config import Settings


def test_max_provider_tracks_defaults_to_200(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")

    settings = Settings()

    assert settings.max_provider_tracks == 200


def test_max_provider_tracks_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")
    monkeypatch.setenv("MAX_PROVIDER_TRACKS", "75")

    settings = Settings()

    assert settings.max_provider_tracks == 75
