from __future__ import annotations

from datetime import timezone
from pathlib import Path

from .models import RunReport


class Reporter:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def write(self, report: RunReport) -> Path:
        last_run_path = self.state_dir / "last_run.txt"
        started_at = report.started_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        finished_at = report.finished_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        text = "\n".join(
            [
                f"started_at={started_at}",
                f"finished_at={finished_at}",
                f"provider={report.provider}",
                f"user_count_seen={report.user_count_seen}",
                f"targeted_user_count={report.targeted_user_count}",
                f"artist_count_seen={report.artist_count_seen}",
                f"eligible_artist_count={report.eligible_artist_count}",
                f"created_playlist_count={report.created_playlist_count}",
                f"replaced_playlist_count={report.replaced_playlist_count}",
                f"orphan_deleted_count={report.orphan_deleted_count}",
                f"failed_user_count={report.failed_user_count}",
                f"failed_artist_count={report.failed_artist_count}",
            ]
        )
        last_run_path.write_text(text + "\n", encoding="utf-8")
        return last_run_path
