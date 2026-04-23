from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from .config import Settings
from .jellyfin import JellyfinClient
from .logging_setup import configure_logging
from .planner import Planner
from .providers.lastfm import LastFmProvider
from .reporter import Reporter

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
                max_tracks=settings.max_provider_tracks,
            )
            provider = LastFmProvider(
                api_key=settings.lastfm_api_key,
                timeout_seconds=settings.request_timeout_seconds,
                max_retries=settings.request_max_retries,
                retry_backoff_seconds=settings.retry_backoff_seconds,
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
        "created=%s replaced=%s failed_users=%s failed_artists=%s",
        report.user_count_seen,
        report.targeted_user_count,
        report.artist_count_seen,
        report.eligible_artist_count,
        report.created_playlist_count,
        report.replaced_playlist_count,
        report.failed_user_count,
        report.failed_artist_count,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
