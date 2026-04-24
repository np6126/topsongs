import unittest
from unittest.mock import MagicMock, patch

from topsongs.filters import LibraryPathFilter
from topsongs.models import (
    JellyfinArtist,
    JellyfinPlaylist,
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
    playlist_name_prefix = "Top Songs - "


class LibraryPathFilterTests(unittest.TestCase):
    def test_filters_tracks_by_path_prefix(self) -> None:
        path_filter = LibraryPathFilter(
            allowlist=SettingsStub.library_path_allowlist,
            denylist=SettingsStub.library_path_denylist,
        )
        tracks = [
            JellyfinTrack(id="1", name="song1", path="/music/metal/song1.flac"),
            JellyfinTrack(id="2", name="song2", path="/music/podcasts/episode1.mp3"),
            JellyfinTrack(id="3", name="song3", path="/audiobooks/book1/ch1.mp3"),
            JellyfinTrack(id="4", name="song4", path=None),
        ]

        filtered = path_filter.filter_tracks(tracks)

        self.assertEqual([track.id for track in filtered], ["1"])

    def test_path_matching_handles_case_and_boundaries(self) -> None:
        path_filter = LibraryPathFilter(
            allowlist=SettingsStub.library_path_allowlist,
            denylist=SettingsStub.library_path_denylist,
        )

        self.assertTrue(path_filter.matches("/music/artist/song.mp3"))
        self.assertFalse(path_filter.matches("/musicbox/artist/song.mp3"))
        self.assertFalse(path_filter.matches("/music/podcasts/episode.mp3"))

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

    def test_playlist_name_uses_configured_prefix(self) -> None:
        class PrefixedSettings(SettingsStub):
            playlist_name_prefix = "Best Of - "

        planner = Planner(PrefixedSettings(), jellyfin=None, provider=MagicMock(name="lastfm"))

        self.assertEqual(planner._playlist_name("Powerwolf"), "Best Of - Powerwolf")

    def test_deletes_orphan_managed_playlists_after_planning(self) -> None:
        class JellyfinStub:
            def __init__(self) -> None:
                self.deleted_ids = []

            def get_artists(self, user_id):
                return [JellyfinArtist(id="a1", name="Powerwolf")]

            def get_playlists_for_user(self, user_id):
                return [
                    JellyfinPlaylist(id="p1", name="Top Songs - Powerwolf"),
                    JellyfinPlaylist(id="p2", name="Top Songs - Blind Guardian"),
                    JellyfinPlaylist(id="p3", name="Favorites"),
                ]

            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(id=str(index), name=f"song{index}", path=f"/music/song{index}.flac")
                    for index in range(1, 12)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "playlist-new"

            def delete_playlist(self, playlist_id):
                self.deleted_ids.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="song1", rank=1)]
        jellyfin = JellyfinStub()
        planner = Planner(SettingsStub(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(user_plan.planned_playlist_count, 1)
        self.assertEqual(user_plan.orphan_deleted_count, 1)
        self.assertEqual(set(jellyfin.deleted_ids), {"p1", "p2"})

    def test_orphan_cleanup_respects_configured_prefix(self) -> None:
        class PrefixedSettings(SettingsStub):
            playlist_name_prefix = "Best Of - "

        class JellyfinStub:
            def __init__(self) -> None:
                self.deleted_ids = []

            def get_artists(self, user_id):
                return []

            def get_playlists_for_user(self, user_id):
                return [
                    JellyfinPlaylist(id="p1", name="Best Of - Blind Guardian"),
                    JellyfinPlaylist(id="p2", name="Top Songs - Legacy"),
                    JellyfinPlaylist(id="p3", name="Favorites"),
                ]

            def delete_playlist(self, playlist_id):
                self.deleted_ids.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        jellyfin = JellyfinStub()
        planner = Planner(PrefixedSettings(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(user_plan.orphan_deleted_count, 1)
        self.assertEqual(jellyfin.deleted_ids, ["p1"])

    def test_existing_playlist_is_deleted_when_artist_is_no_longer_eligible(self) -> None:
        class JellyfinStub:
            def __init__(self) -> None:
                self.deleted_ids = []

            def get_artists(self, user_id):
                return [JellyfinArtist(id="a1", name="Powerwolf")]

            def get_playlists_for_user(self, user_id):
                return [JellyfinPlaylist(id="p1", name="Top Songs - Powerwolf")]

            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(id=str(index), name=f"song{index}", path=f"/music/song{index}.flac")
                    for index in range(1, 11)
                ]

            def delete_playlist(self, playlist_id):
                self.deleted_ids.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        jellyfin = JellyfinStub()
        planner = Planner(SettingsStub(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(user_plan.planned_playlist_count, 0)
        self.assertEqual(user_plan.orphan_deleted_count, 1)
        self.assertEqual(jellyfin.deleted_ids, ["p1"])

    def test_orphan_delete_failure_is_isolated(self) -> None:
        class JellyfinStub:
            def get_artists(self, user_id):
                return []

            def get_playlists_for_user(self, user_id):
                return [JellyfinPlaylist(id="p1", name="Top Songs - Powerwolf")]

            def delete_playlist(self, playlist_id):
                raise RuntimeError("delete failed")

        provider = MagicMock()
        provider.name = "lastfm"
        planner = Planner(SettingsStub(), jellyfin=JellyfinStub(), provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(user_plan.orphan_deleted_count, 0)
        self.assertIn("Failed to delete orphan playlist p1 (Top Songs - Powerwolf): delete failed", user_plan.notes)


if __name__ == "__main__":
    unittest.main()
