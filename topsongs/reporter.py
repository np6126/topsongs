from __future__ import annotations

from datetime import timezone
from pathlib import Path

from .models import ArtistPlan, RunReport


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
                f"unmatched_local_track_count={report.unmatched_local_track_count}",
            ]
        )
        unmatched_lines = self._format_unmatched_tracks(report)
        if unmatched_lines:
            text += "\n" + "\n".join(unmatched_lines)
        last_run_path.write_text(text + "\n", encoding="utf-8")
        return last_run_path

    @staticmethod
    def _format_unmatched_tracks(report: RunReport) -> list[str]:
        lines: list[str] = []
        local_lines: list[str] = []
        seen_local_tracks: set[tuple[str, str]] = set()

        for user in report.users:
            for artist in user.artists:
                for track_title in artist.unmatched_local_tracks:
                    local_key = (artist.artist, track_title)
                    if local_key in seen_local_tracks:
                        continue
                    seen_local_tracks.add(local_key)
                    local_lines.append(
                        Reporter._format_local_track_detail(
                            artist=artist,
                            track_title=track_title,
                        )
                    )

        if local_lines:
            lines.append("unmatched_local_tracks:")
            lines.extend(local_lines)
        return lines

    @staticmethod
    def _format_local_track_detail(
        artist: ArtistPlan,
        track_title: str,
    ) -> str:
        return f"- unmatched_local: {artist.artist} - {track_title}"
