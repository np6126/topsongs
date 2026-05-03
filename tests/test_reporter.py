from datetime import datetime, timezone

from topsongs.models import ArtistPlan, RunReport, UserPlan
from topsongs.reporter import Reporter


def test_last_run_includes_unmatched_counts_and_details(tmp_path) -> None:
    report = RunReport(
        started_at=datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 3, 10, 1, tzinfo=timezone.utc),
        provider="lastfm",
        user_count_seen=2,
        targeted_user_count=2,
        artist_count_seen=2,
        eligible_artist_count=2,
        created_playlist_count=2,
        replaced_playlist_count=0,
        users=[
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
        ],
    )

    path = Reporter(tmp_path).write(report)

    text = path.read_text(encoding="utf-8")
    assert "unmatched_local_track_count=1" in text
    assert (
        "unmatched_local_tracks:\n"
        "- unmatched_local: Powerwolf - Sanctified with Dynamite"
    ) in text
    assert "unmatched_tracks:" not in text
    assert text.count("unmatched_local: Powerwolf - Sanctified with Dynamite") == 1
