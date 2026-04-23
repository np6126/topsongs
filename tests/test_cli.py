from pathlib import Path
from types import SimpleNamespace

from topsongs import cli
from topsongs.models import RunReport


def test_main_passes_max_tracks_only_to_lastfm_provider(monkeypatch, tmp_path) -> None:
    jellyfin_kwargs = {}
    lastfm_kwargs = {}

    class SettingsStub:
        jellyfin_url = "http://jellyfin:8096"
        jellyfin_api_key = "jellyfin-key"
        lastfm_api_key = "lastfm-key"
        request_timeout_seconds = 20
        request_max_retries = 2
        retry_backoff_seconds = 1.0
        max_provider_tracks = 75
        state_dir = tmp_path
        log_level = "INFO"

    class JellyfinClientStub:
        def __init__(self, **kwargs) -> None:
            jellyfin_kwargs.update(kwargs)

    class LastFmProviderStub:
        name = "lastfm"

        def __init__(self, **kwargs) -> None:
            lastfm_kwargs.update(kwargs)

    class PlannerStub:
        def __init__(self, settings, jellyfin, provider) -> None:
            pass

        def run(self) -> RunReport:
            return RunReport.empty(provider="lastfm")

    class ReporterStub:
        def __init__(self, state_dir: Path) -> None:
            pass

        def write(self, report: RunReport) -> Path:
            return tmp_path / "last_run.txt"

    monkeypatch.setattr(cli, "Settings", SettingsStub)
    monkeypatch.setattr(cli, "JellyfinClient", JellyfinClientStub)
    monkeypatch.setattr(cli, "LastFmProvider", LastFmProviderStub)
    monkeypatch.setattr(cli, "Planner", PlannerStub)
    monkeypatch.setattr(cli, "Reporter", ReporterStub)
    monkeypatch.setattr(cli, "configure_logging", lambda level: None)
    monkeypatch.setattr(cli, "acquire_run_lock", lambda state_dir: _NullContext())

    assert cli.main() == 0

    assert "max_tracks" not in jellyfin_kwargs
    assert lastfm_kwargs["max_tracks"] == 75


class _NullContext:
    def __enter__(self) -> SimpleNamespace:
        return SimpleNamespace()

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None
