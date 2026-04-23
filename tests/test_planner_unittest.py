import unittest
from unittest.mock import MagicMock, patch

from topsongs.models import (
    JellyfinArtist,
    JellyfinTrack,
    JellyfinUser,
    JellyfinUserPolicy,
    ProviderTrack,
)
from topsongs.planner import Planner


class SettingsStub:
    library_path_allowlist = ["/music"]
    library_path_denylist = ["/music/podcasts"]
    artist_allowlist = []
    artist_denylist = []
    user_allowlist = []
    user_denylist = []
    min_tracks_per_artist = 10


class PlannerPathFilterTests(unittest.TestCase):
    def test_filters_tracks_by_path_prefix(self) -> None:
        planner = Planner(SettingsStub(), jellyfin=None, provider=None)
        tracks = [
            JellyfinTrack(id="1", name="song1", path="/music/metal/song1.flac"),
            JellyfinTrack(id="2", name="song2", path="/music/podcasts/episode1.mp3"),
            JellyfinTrack(id="3", name="song3", path="/audiobooks/book1/ch1.mp3"),
            JellyfinTrack(id="4", name="song4", path=None),
        ]

        filtered = planner._filter_tracks_by_library_path(tracks)

        self.assertEqual([track.id for track in filtered], ["1"])

    def test_path_matching_handles_case_and_boundaries(self) -> None:
        planner = Planner(SettingsStub(), jellyfin=None, provider=None)

        self.assertTrue(planner._path_is_selected("/music/artist/song.mp3"))
        self.assertFalse(planner._path_is_selected("/musicbox/artist/song.mp3"))
        self.assertFalse(planner._path_is_selected("/music/podcasts/episode.mp3"))

    def test_logs_human_readable_playlist_tracks(self) -> None:
        planner = Planner(SettingsStub(), jellyfin=None, provider=None)
        with patch("topsongs.planner.logger") as logger:
            planner._log_applied_playlist(
                "jaji",
                "Top Songs - Powerwolf",
                "created",
                "playlist-123",
                [
                    type(
                        "Track",
                        (),
                        {
                            "rank": 1,
                            "jellyfin_title": "Army of the Night",
                            "provider_title": "Army of the Night",
                            "match_type": "exact",
                            "album": "Blessed & Possessed",
                        },
                    )(),
                    type(
                        "Track",
                        (),
                        {
                            "rank": 2,
                            "jellyfin_title": "We Drink Your Blood",
                            "provider_title": "We Drink Your Blood - Remastered 2018",
                            "match_type": "normalized",
                            "album": "Preachers of the Night",
                        },
                    )(),
                ],
            )

        messages = [call.args[0] for call in logger.info.call_args_list]
        self.assertIn(
            "event=playlist_applied user=%s playlist=%s action=%s playlist_id=%s track_count=%s",
            messages[0],
        )
        self.assertIn("  1. Army of the Night [exact] (Blessed & Possessed)", messages[1])
        self.assertIn(
            "  2. We Drink Your Blood <- We Drink Your Blood - Remastered 2018 "
            "[normalized] (Preachers of the Night)",
            messages[2],
        )

    def test_provider_tracks_are_cached_per_run(self) -> None:
        provider = MagicMock()
        provider.get_top_tracks.return_value = [ProviderTrack(title="Army of the Night", rank=1)]
        planner = Planner(SettingsStub(), jellyfin=None, provider=provider)

        first = planner._get_provider_tracks("Powerwolf")
        second = planner._get_provider_tracks("Powerwolf")

        self.assertEqual(first, second)
        provider.get_top_tracks.assert_called_once_with("Powerwolf")

    def test_artist_failure_is_isolated(self) -> None:
        class JellyfinStub:
            def get_artists(self, user_id):
                return [JellyfinArtist(id="a1", name="Broken Artist")]

            def get_playlists_for_user(self, user_id):
                return []

            def get_tracks_for_artist(self, user_id, artist):
                raise RuntimeError("track lookup failed")

        provider = MagicMock()
        provider.name = "lastfm"
        planner = Planner(SettingsStub(), jellyfin=JellyfinStub(), provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(user_plan.failed_artist_count, 1)
        self.assertEqual(len(user_plan.artists), 1)
        self.assertEqual(user_plan.artists[0].error, "track lookup failed")


if __name__ == "__main__":
    unittest.main()
