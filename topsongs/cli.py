from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from .config import Settings
from .jellyfin import JellyfinClient
from .logging_setup import configure_logging
from .models import RunReport
from .planner import Planner
from .providers.lastfm import LastFmProvider
from .reporter import Reporter
from .sanitize import sanitize_untrusted_text

logger = logging.getLogger(__name__)


class RunAlreadyActiveError(RuntimeError):
    pass


@contextmanager
def acquire_run_lock(state_dir: Path):
    lock_path = state_dir / ".run.lock"
    fd: int | None = None
    acquired = False
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
            handle.write("\n")
        fd = None
        acquired = True
        yield lock_path
    except FileExistsError as exc:
        raise RunAlreadyActiveError(
            f"Another run is already active: lock_path={lock_path}"
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)
        if acquired and lock_path.exists():
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def main() -> int:
    settings = Settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.log_level)
    logger.info("event=start state_dir=%s", settings.state_dir)

    try:
        with acquire_run_lock(settings.state_dir):
            jellyfin = JellyfinClient(
                base_url=settings.jellyfin_url,
                api_key=settings.jellyfin_api_key,
                timeout_seconds=settings.request_timeout_seconds,
                max_retries=settings.request_max_retries,
                retry_backoff_seconds=settings.retry_backoff_seconds,
            )
            provider = LastFmProvider(
                api_key=settings.lastfm_api_key,
                timeout_seconds=settings.request_timeout_seconds,
                max_retries=settings.request_max_retries,
                retry_backoff_seconds=settings.retry_backoff_seconds,
                max_tracks=settings.max_provider_tracks,
            )
            planner = Planner(settings=settings, jellyfin=jellyfin, provider=provider)
            report = planner.run()
    except RunAlreadyActiveError as exc:
        logger.warning("event=skip reason=run_lock error=%s", exc)
        return 0

    reporter = Reporter(settings.state_dir)
    last_run_path = reporter.write(report)

    logger.info("event=finish last_run_path=%s", last_run_path)
    logger.info(
        "event=summary users_seen=%s targeted_users=%s artists_seen=%s eligible=%s "
        "created=%s replaced=%s orphan_deleted=%s failed_users=%s failed_artists=%s "
        "unmatched_local=%s",
        report.user_count_seen,
        report.targeted_user_count,
        report.artist_count_seen,
        report.eligible_artist_count,
        report.created_playlist_count,
        report.replaced_playlist_count,
        report.orphan_deleted_count,
        report.failed_user_count,
        report.failed_artist_count,
        report.unmatched_local_track_count,
    )
    _log_unmatched_summary(report)
    return 0


def _log_unmatched_summary(report: RunReport) -> None:
    seen_local_tracks: set[tuple[str, str]] = set()

    for user in report.users:
        for artist in user.artists:
            safe_artist = sanitize_untrusted_text(artist.artist)
            for track_title in artist.unmatched_local_tracks:
                local_key = (artist.artist, track_title)
                if local_key in seen_local_tracks:
                    continue
                seen_local_tracks.add(local_key)
                logger.info(
                    "event=summary_unmatched type=local artist=%s track=%s",
                    safe_artist,
                    sanitize_untrusted_text(track_title),
                )


if __name__ == "__main__":
    sys.exit(main())
