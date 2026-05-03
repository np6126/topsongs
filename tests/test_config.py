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


def test_playlist_name_prefix_defaults_to_top_songs(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")

    settings = Settings()

    assert settings.playlist_name_prefix == "Top Songs - "


def test_playlist_name_prefix_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")
    monkeypatch.setenv("PLAYLIST_NAME_PREFIX", "Best Of - ")

    settings = Settings()

    assert settings.playlist_name_prefix == "Best Of - "


def test_append_unmatched_songs_defaults_to_true(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")

    settings = Settings()

    assert settings.append_unmatched_songs is True


def test_append_unmatched_songs_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")
    monkeypatch.setenv("APPEND_UNMATCHED_SONGS", "false")

    settings = Settings()

    assert settings.append_unmatched_songs is False


def test_append_unmatched_songs_accepts_lowercase_env_name(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")
    monkeypatch.setenv("append_unmatched_songs", "false")

    settings = Settings()

    assert settings.append_unmatched_songs is False


def test_min_track_duration_seconds_defaults_to_60(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")

    settings = Settings()

    assert settings.min_track_duration_seconds == 60


def test_min_track_duration_seconds_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")
    monkeypatch.setenv("MIN_TRACK_DURATION_SECONDS", "45")

    settings = Settings()

    assert settings.min_track_duration_seconds == 45
