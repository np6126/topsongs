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


def test_personalization_weight_defaults_to_0_6(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")

    settings = Settings()

    assert settings.personalization_weight == 0.6


def test_personalization_weight_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")
    monkeypatch.setenv("PERSONALIZATION_WEIGHT", "0.25")

    settings = Settings()

    assert settings.personalization_weight == 0.25


def test_personalization_weight_is_clamped_to_unit_range(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")

    monkeypatch.setenv("PERSONALIZATION_WEIGHT", "5")
    assert Settings().personalization_weight == 1.0

    monkeypatch.setenv("PERSONALIZATION_WEIGHT", "-2")
    assert Settings().personalization_weight == 0.0


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


def test_run_concurrency_defaults_to_1(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")

    settings = Settings()

    assert settings.run_concurrency == 1


def test_run_concurrency_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")
    monkeypatch.setenv("RUN_CONCURRENCY", "4")

    settings = Settings()

    assert settings.run_concurrency == 4


def test_run_concurrency_is_clamped_to_supported_range(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")

    monkeypatch.setenv("RUN_CONCURRENCY", "0")
    assert Settings().run_concurrency == 1

    monkeypatch.setenv("RUN_CONCURRENCY", "99")
    assert Settings().run_concurrency == 16

    monkeypatch.setenv("RUN_CONCURRENCY", "-5")
    assert Settings().run_concurrency == 1


def test_min_request_interval_defaults_to_0(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")

    settings = Settings()

    assert settings.min_request_interval == 0.0


def test_min_request_interval_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")
    monkeypatch.setenv("MIN_REQUEST_INTERVAL", "0.25")

    settings = Settings()

    assert settings.min_request_interval == 0.25


def test_min_request_interval_is_clamped_to_non_negative(monkeypatch) -> None:
    monkeypatch.setenv("JELLYFIN_URL", "http://jellyfin:8096")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jellyfin-key")
    monkeypatch.setenv("LASTFM_API_KEY", "lastfm-key")
    monkeypatch.setenv("MIN_REQUEST_INTERVAL", "-1.5")

    settings = Settings()

    assert settings.min_request_interval == 0.0
