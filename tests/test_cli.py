from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from topsongs import cli
from topsongs.models import ArtistPlan, RunReport, UserPlan


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
        dry_run = False

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


def test_unmatched_summary_logs_details(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(cli, "logger", logger)
    report = RunReport.empty(provider="lastfm")
    report.users = [
        UserPlan(
            user_id="u1",
            user_name="Alice",
            is_administrator=False,
            artist_count_seen=1,
            eligible_artist_count=1,
            planned_playlist_count=1,
            artists=[
                ArtistPlan(
                    artist="Powerwolf",
                    local_track_count=11,
                    eligible=True,
                    provider="lastfm",
                    unmatched_local_tracks=["Sanctified with Dynamite"],
                )
            ],
        ),
        UserPlan(
            user_id="u2",
            user_name="Bob",
            is_administrator=False,
            artist_count_seen=1,
            eligible_artist_count=1,
            planned_playlist_count=1,
            artists=[
                ArtistPlan(
                    artist="Powerwolf",
                    local_track_count=11,
                    eligible=True,
                    provider="lastfm",
                    unmatched_local_tracks=["Sanctified with Dynamite"],
                )
            ],
        ),
    ]

    cli._log_unmatched_summary(report)

    logger.info.assert_any_call(
        "event=summary_unmatched type=local artist=%s track=%s",
        "Powerwolf",
        "Sanctified with Dynamite",
    )
    local_calls = [
        call
        for call in logger.info.call_args_list
        if call.args[0] == "event=summary_unmatched type=local artist=%s track=%s"
    ]
    assert len(local_calls) == 1
    provider_calls = [
        call
        for call in logger.info.call_args_list
        if "type=provider" in call.args[0]
    ]
    assert not provider_calls


def test_main_returns_nonzero_when_artists_failed(monkeypatch, tmp_path) -> None:
    """Fix 2: non-zero exit code when failed_artist_count > 0."""

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
        dry_run = False

    report = RunReport.empty(provider="lastfm")
    report = report.model_copy(update={"failed_artist_count": 1})

    class PlannerStub:
        def __init__(self, settings, jellyfin, provider) -> None:
            pass

        def run(self) -> RunReport:
            return report

    class ReporterStub:
        def __init__(self, state_dir: Path) -> None:
            pass

        def write(self, r: RunReport) -> Path:
            return tmp_path / "last_run.txt"

    monkeypatch.setattr(cli, "Settings", SettingsStub)
    monkeypatch.setattr(cli, "JellyfinClient", MagicMock)
    monkeypatch.setattr(cli, "LastFmProvider", MagicMock)
    monkeypatch.setattr(cli, "Planner", PlannerStub)
    monkeypatch.setattr(cli, "Reporter", ReporterStub)
    monkeypatch.setattr(cli, "configure_logging", lambda level: None)
    monkeypatch.setattr(cli, "acquire_run_lock", lambda state_dir: _NullContext())

    assert cli.main() == 1


def test_main_writes_report_and_returns_nonzero_when_planner_raises(monkeypatch, tmp_path) -> None:
    """Fix 3: last_run.txt must be written and exit code must be 1 even if planner.run() throws."""

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
        dry_run = False

    written_reports = []

    class PlannerStub:
        def __init__(self, settings, jellyfin, provider) -> None:
            pass

        def run(self) -> RunReport:
            raise RuntimeError("jellyfin unreachable")

    class ReporterStub:
        def __init__(self, state_dir: Path) -> None:
            pass

        def write(self, report: RunReport) -> Path:
            written_reports.append(report)
            return tmp_path / "last_run.txt"

    monkeypatch.setattr(cli, "Settings", SettingsStub)
    monkeypatch.setattr(cli, "JellyfinClient", MagicMock)
    monkeypatch.setattr(cli, "LastFmProvider", MagicMock)
    monkeypatch.setattr(cli, "Planner", PlannerStub)
    monkeypatch.setattr(cli, "Reporter", ReporterStub)
    monkeypatch.setattr(cli, "configure_logging", lambda level: None)
    monkeypatch.setattr(cli, "acquire_run_lock", lambda state_dir: _NullContext())

    result = cli.main()

    assert result == 1
    assert len(written_reports) == 1


def test_stale_lock_is_cleared_before_acquisition(tmp_path) -> None:
    """Fix 4: lock files older than the stale threshold are removed automatically."""
    import time as _time

    lock_path = tmp_path / ".run.lock"
    lock_path.write_text("99999\n", encoding="utf-8")
    old_mtime = _time.time() - cli._STALE_LOCK_SECONDS - 1
    import os as _os
    _os.utime(lock_path, (old_mtime, old_mtime))

    cli._maybe_clear_stale_lock(lock_path)

    assert not lock_path.exists()


def test_fresh_lock_is_not_cleared(tmp_path) -> None:
    """Fix 4: a recent lock file must not be auto-deleted."""
    lock_path = tmp_path / ".run.lock"
    lock_path.write_text("99999\n", encoding="utf-8")

    cli._maybe_clear_stale_lock(lock_path)

    assert lock_path.exists()


class _NullContext:
    def __enter__(self) -> SimpleNamespace:
        return SimpleNamespace()

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None
