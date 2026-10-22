import itertools
import threading
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
    min_track_duration_seconds = 60
    playlist_name_prefix = "Top Songs - "
    playlist_managed_tag = "topsongs"
    append_unmatched_songs = True
    personalization_weight = 0.0
    recency_bonus = None
    dry_run = False
    run_concurrency = 1


class BareNameSettings(SettingsStub):
    # No name prefix: the playlists are named after the artist alone.
    playlist_name_prefix = ""


class TaggingStub:
    """Base for the Jellyfin stubs: accepts the tag every created playlist gets."""

    def add_managed_tag(self, user_id, playlist_id, tag):
        pass


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
                "Alice",
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
                            "play_count": 0,
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
                            "play_count": 7,
                        },
                    )(),
                ],
            )

        info_messages = [call.args[0] for call in logger.info.call_args_list]
        track_messages = [call.args[0] for call in logger.debug.call_args_list]
        self.assertIn(
            "event=playlist_applied user=%s playlist=%s action=%s playlist_id=%s track_count=%s",
            info_messages[0],
        )
        self.assertIn("  1. Army of the Night [exact] (Blessed & Possessed)", track_messages[0])
        self.assertIn(
            "  2. We Drink Your Blood <- We Drink Your Blood - Remastered 2018 "
            "[normalized] plays=7 (Preachers of the Night)",
            track_messages[1],
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
        class JellyfinStub(TaggingStub):
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

    def test_playlist_name_sanitizes_illegal_filename_chars(self) -> None:
        planner = Planner(SettingsStub(), jellyfin=None, provider=MagicMock(name="lastfm"))

        self.assertEqual(planner._playlist_name("AC/DC"), "Top Songs - AC_DC")

    def test_deletes_orphan_managed_playlists_after_planning(self) -> None:
        class JellyfinStub(TaggingStub):
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
                    JellyfinTrack(
                        id=str(index),
                        name=f"song{index}",
                        path=f"/music/song{index}.flac",
                    )
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

        class JellyfinStub(TaggingStub):
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

    def test_tag_mode_uses_bare_name_and_tags_created_playlist(self) -> None:
        """Tag mode: the playlist name has no prefix and the create is tagged."""

        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.tagged: list[tuple[str, str, str]] = []

            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(id=str(i), name=f"song{i}", path=f"/music/{i}.flac")
                    for i in range(1, 12)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "new-id"

            def add_managed_tag(self, user_id, playlist_id, tag):
                self.tagged.append((user_id, playlist_id, tag))

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="song1", rank=1)]
        jellyfin = JellyfinStub()
        planner = Planner(BareNameSettings(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())
        artist = JellyfinArtist(id="a1", name="Powerwolf")

        artist_plan = planner._plan_for_artist(user, artist, existing_playlists={})

        self.assertEqual(artist_plan.playlist_plan.playlist_name, "Powerwolf")
        self.assertEqual(jellyfin.tagged, [("u1", "new-id", "topsongs")])

    def test_tag_mode_orphan_deletes_tagged_but_leaves_untagged_same_name(self) -> None:
        """Tag mode: a tagged orphan is deleted; an untagged same-name user playlist is not."""

        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.deleted: list[str] = []

            def get_artists(self, user_id):
                return []

            def get_playlists_for_user(self, user_id):
                return [
                    JellyfinPlaylist(id="p1", name="Nightwish", tags=["topsongs"]),
                    JellyfinPlaylist(id="p2", name="Nightwish", tags=[]),
                ]

            def delete_playlist(self, playlist_id):
                self.deleted.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        jellyfin = JellyfinStub()
        planner = Planner(BareNameSettings(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(user_plan.orphan_deleted_count, 1)
        self.assertEqual(jellyfin.deleted, ["p1"])

    def test_tag_mode_replace_matches_only_tagged_playlist(self) -> None:
        """Tag mode: a re-run replaces the tagged playlist and leaves the untagged twin."""

        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.deleted: list[str] = []
                self.tagged: list[tuple[str, str, str]] = []

            def get_artists(self, user_id):
                return [JellyfinArtist(id="a1", name="Powerwolf")]

            def get_playlists_for_user(self, user_id):
                return [
                    JellyfinPlaylist(id="pu", name="Powerwolf", tags=[]),
                    JellyfinPlaylist(id="pt", name="Powerwolf", tags=["topsongs"]),
                ]

            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(id=str(i), name=f"song{i}", path=f"/music/{i}.flac")
                    for i in range(1, 12)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "new-id"

            def add_managed_tag(self, user_id, playlist_id, tag):
                self.tagged.append((user_id, playlist_id, tag))

            def delete_playlist(self, playlist_id):
                self.deleted.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="song1", rank=1)]
        jellyfin = JellyfinStub()
        planner = Planner(BareNameSettings(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(user_plan.planned_playlist_count, 1)
        # Only the tagged twin is replaced (deleted); the untagged user playlist survives.
        self.assertEqual(jellyfin.deleted, ["pt"])
        self.assertEqual(jellyfin.tagged, [("u1", "new-id", "topsongs")])
        playlist_plan = user_plan.artists[0].playlist_plan
        self.assertEqual(playlist_plan.action, "replaced")
        self.assertEqual(playlist_plan.playlist_name, "Powerwolf")

    def test_tag_mode_rolls_back_created_playlist_when_tagging_fails(self) -> None:
        """Tag mode: a failed tag deletes the just-created playlist so no untagged
        orphan leaks, and the artist is reported as failed."""

        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.deleted: list[str] = []

            def get_artists(self, user_id):
                return [JellyfinArtist(id="a1", name="Powerwolf")]

            def get_playlists_for_user(self, user_id):
                return []

            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(id=str(i), name=f"song{i}", path=f"/music/{i}.flac")
                    for i in range(1, 12)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "new-id"

            def add_managed_tag(self, user_id, playlist_id, tag):
                raise RuntimeError("tag write failed")

            def delete_playlist(self, playlist_id):
                self.deleted.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="song1", rank=1)]
        jellyfin = JellyfinStub()
        planner = Planner(BareNameSettings(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        # The untagged playlist is rolled back, not left behind as an orphan.
        self.assertEqual(jellyfin.deleted, ["new-id"])
        self.assertEqual(user_plan.failed_artist_count, 1)
        self.assertEqual(user_plan.planned_playlist_count, 0)
        self.assertEqual(user_plan.artists[0].error, "tag write failed")

    def test_existing_playlist_is_deleted_when_artist_is_no_longer_eligible(self) -> None:
        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.deleted_ids = []

            def get_artists(self, user_id):
                return [JellyfinArtist(id="a1", name="Powerwolf")]

            def get_playlists_for_user(self, user_id):
                return [JellyfinPlaylist(id="p1", name="Top Songs - Powerwolf")]

            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(
                        id=str(index),
                        name=f"song{index}",
                        path=f"/music/song{index}.flac",
                    )
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

    def test_artist_plan_reports_local_tracks_not_present_in_provider_list(self) -> None:
        class JellyfinStub(TaggingStub):
            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(
                        id=str(index),
                        name=f"song{index}",
                        path=f"/music/song{index}.flac",
                    )
                    for index in range(1, 12)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "playlist-new"

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="song1", rank=1)]
        planner = Planner(SettingsStub(), jellyfin=JellyfinStub(), provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())
        artist = JellyfinArtist(id="a1", name="Powerwolf")

        artist_plan = planner._plan_for_artist(user, artist, existing_playlists={})

        self.assertEqual(
            artist_plan.unmatched_local_tracks,
            [f"song{index}" for index in range(2, 12)],
        )
        self.assertEqual(
            artist_plan.playlist_plan.planned_item_ids,
            [str(index) for index in range(1, 12)],
        )
        self.assertEqual(
            [track.match_type for track in artist_plan.playlist_plan.planned_tracks],
            ["exact", *["unmatched_local" for _ in range(2, 12)]],
        )

    def test_unmatched_local_tracks_can_be_excluded_from_playlist(self) -> None:
        class SettingsWithoutAppend(SettingsStub):
            append_unmatched_songs = False

        class JellyfinStub(TaggingStub):
            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(
                        id=str(index),
                        name=f"song{index}",
                        path=f"/music/song{index}.flac",
                    )
                    for index in range(1, 12)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "playlist-new"

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="song1", rank=1)]
        planner = Planner(SettingsWithoutAppend(), jellyfin=JellyfinStub(), provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())
        artist = JellyfinArtist(id="a1", name="Powerwolf")

        artist_plan = planner._plan_for_artist(user, artist, existing_playlists={})

        self.assertEqual(
            artist_plan.unmatched_local_tracks,
            [f"song{index}" for index in range(2, 12)],
        )
        self.assertEqual(artist_plan.playlist_plan.planned_item_ids, ["1"])
        self.assertEqual(
            [track.match_type for track in artist_plan.playlist_plan.planned_tracks],
            ["exact"],
        )

    def test_short_tracks_are_excluded_from_playlist_and_eligibility(self) -> None:
        class JellyfinStub(TaggingStub):
            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(
                        id=str(index),
                        name=f"song{index}",
                        path=f"/music/song{index}.flac",
                        runtime_ticks=61 * 10_000_000,
                    )
                    for index in range(1, 12)
                ] + [
                    JellyfinTrack(
                        id="clip",
                        name="clip",
                        path="/music/clip.flac",
                        runtime_ticks=59 * 10_000_000,
                    )
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "playlist-new"

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [
            ProviderTrack(title="song1", rank=1),
            ProviderTrack(title="clip", rank=2),
        ]
        planner = Planner(SettingsStub(), jellyfin=JellyfinStub(), provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())
        artist = JellyfinArtist(id="a1", name="Powerwolf")

        artist_plan = planner._plan_for_artist(user, artist, existing_playlists={})

        self.assertEqual(artist_plan.local_track_count, 11)
        self.assertIn(
            "Excluded 1 local tracks shorter than 60 seconds.",
            artist_plan.notes,
        )
        self.assertNotIn("clip", artist_plan.playlist_plan.planned_item_ids)
        self.assertEqual(
            artist_plan.playlist_plan.planned_item_ids,
            [str(index) for index in range(1, 12)],
        )

    def test_orphan_delete_failure_is_isolated(self) -> None:
        class JellyfinStub(TaggingStub):
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
        self.assertIn(
            "Failed to delete orphan playlist p1 (Top Songs - Powerwolf): delete failed",
            user_plan.notes,
        )


    def test_failed_artist_preserves_existing_playlist_from_orphan_deletion(self) -> None:
        """Fix 1: playlist must not be orphan-deleted when the artist's processing fails."""

        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.deleted_ids: list[str] = []

            def get_artists(self, user_id):
                return [JellyfinArtist(id="a1", name="Powerwolf")]

            def get_playlists_for_user(self, user_id):
                return [JellyfinPlaylist(id="p1", name="Top Songs - Powerwolf")]

            def get_tracks_for_artist(self, user_id, artist):
                raise RuntimeError("last.fm unreachable")

            def delete_playlist(self, playlist_id):
                self.deleted_ids.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        jellyfin = JellyfinStub()
        planner = Planner(SettingsStub(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(user_plan.failed_artist_count, 1)
        self.assertEqual(user_plan.orphan_deleted_count, 0)
        self.assertEqual(jellyfin.deleted_ids, [])

    def test_playlist_name_collision_skips_second_artist(self) -> None:
        """Fix 6: artists that sanitize to the same playlist name must not clobber each other."""

        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.created: list[str] = []

            def get_artists(self, user_id):
                return [
                    JellyfinArtist(id="a1", name="A/B"),
                    JellyfinArtist(id="a2", name="A_B"),
                ]

            def get_playlists_for_user(self, user_id):
                return []

            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(id=f"{artist.id}-{i}", name=f"song{i}", path=f"/music/s{i}.flac")
                    for i in range(1, 12)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                self.created.append(playlist_name)
                return "new-id"

            def delete_playlist(self, playlist_id):
                pass

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="song1", rank=1)]
        jellyfin = JellyfinStub()
        planner = Planner(SettingsStub(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(user_plan.planned_playlist_count, 1)
        self.assertEqual(len(jellyfin.created), 1)
        second = next(p for p in user_plan.artists if p.artist == "A_B")
        self.assertTrue(any("collision" in n for n in second.notes))

    def test_dry_run_skips_create_and_delete(self) -> None:
        """Fix 5: dry_run=True must not call create_playlist or delete_playlist."""

        class DryRunSettings(SettingsStub):
            dry_run = True

        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.created: list[str] = []
                self.deleted: list[str] = []

            def get_artists(self, user_id):
                return [JellyfinArtist(id="a1", name="Powerwolf")]

            def get_playlists_for_user(self, user_id):
                return [JellyfinPlaylist(id="p-old", name="Top Songs - Powerwolf")]

            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(id=str(i), name=f"song{i}", path=f"/music/s{i}.flac")
                    for i in range(1, 12)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                self.created.append(playlist_name)
                return "new-id"

            def delete_playlist(self, playlist_id):
                self.deleted.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="song1", rank=1)]
        jellyfin = JellyfinStub()
        planner = Planner(DryRunSettings(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(jellyfin.created, [])
        self.assertEqual(jellyfin.deleted, [])
        self.assertEqual(user_plan.planned_playlist_count, 1)
        self.assertEqual(user_plan.orphan_deleted_count, 0)

    def test_dry_run_skips_orphan_deletion(self) -> None:
        """Fix 5: orphan playlists must not be deleted in dry_run mode."""

        class DryRunSettings(SettingsStub):
            dry_run = True

        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.deleted: list[str] = []

            def get_artists(self, user_id):
                return []

            def get_playlists_for_user(self, user_id):
                return [JellyfinPlaylist(id="p1", name="Top Songs - Gone")]

            def delete_playlist(self, playlist_id):
                self.deleted.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        jellyfin = JellyfinStub()
        planner = Planner(DryRunSettings(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(jellyfin.deleted, [])
        self.assertEqual(user_plan.orphan_deleted_count, 0)

    def test_unmatched_block_dedups_only_identical_titles(self) -> None:
        """Identical-title copies collapse; distinct editions are kept."""

        class JellyfinStub(TaggingStub):
            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(id="1", name="Wishmaster", path="/music/1.flac"),
                    # Exact-name copy of a matched song (different album): dropped.
                    JellyfinTrack(id="2", name="Wishmaster", path="/music/2.flac"),
                    JellyfinTrack(id="3", name="Amaranth", path="/music/3.flac"),
                    # Distinct editions of an appended song: kept as their own
                    # entries so owning them never drops them from the playlist.
                    JellyfinTrack(id="4", name="Amaranth (Orchestral Version)",
                                  path="/music/4.flac"),
                    JellyfinTrack(id="5", name="Amaranth (Acoustic)",
                                  path="/music/5.flac"),
                ] + [
                    JellyfinTrack(id=str(i), name=f"song{i}", path=f"/music/{i}.flac")
                    for i in range(6, 13)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "playlist-new"

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="Wishmaster", rank=1)]
        planner = Planner(SettingsStub(), jellyfin=JellyfinStub(), provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())
        artist = JellyfinArtist(id="a1", name="Nightwish")

        artist_plan = planner._plan_for_artist(user, artist, existing_playlists={})

        item_ids = artist_plan.playlist_plan.planned_item_ids
        # id 2 (identical-title copy of matched Wishmaster) is the only drop;
        # the distinct Amaranth editions (ids 4/5) are kept.
        self.assertEqual(len(item_ids), len(set(item_ids)))
        self.assertNotIn("2", item_ids)
        self.assertEqual(item_ids[0], "1")
        self.assertIn("3", item_ids)
        self.assertIn("4", item_ids)
        self.assertIn("5", item_ids)
        self.assertEqual(artist_plan.duplicate_local_tracks, ["Wishmaster"])

    def test_distinct_editions_kept_only_identical_titles_are_duplicates(self) -> None:
        """Report: editions become gaps; only identical titles are duplicates."""

        class JellyfinStub(TaggingStub):
            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(id="1", name="Wishmaster", path="/music/1.flac"),
                    # Identical-title copy of the matched song: a real duplicate.
                    JellyfinTrack(id="2", name="Wishmaster", path="/music/2.flac"),
                    # Distinct editions: kept as their own appended entries.
                    JellyfinTrack(id="3", name="Wishmaster (Live)", path="/music/3.flac"),
                    JellyfinTrack(id="4", name="Amaranth", path="/music/4.flac"),
                    JellyfinTrack(id="5", name="Amaranth (Demo)", path="/music/5.flac"),
                ] + [
                    JellyfinTrack(id=str(i), name=f"deepcut{i}", path=f"/music/{i}.flac")
                    for i in range(6, 13)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "playlist-new"

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="Wishmaster", rank=1)]
        planner = Planner(SettingsStub(), jellyfin=JellyfinStub(), provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())
        artist = JellyfinArtist(id="a1", name="Nightwish")

        artist_plan = planner._plan_for_artist(user, artist, existing_playlists={})

        # Only the identical-title copy of Wishmaster is a duplicate.
        self.assertEqual(artist_plan.duplicate_local_tracks, ["Wishmaster"])
        # Editions and unranked deep cuts are all kept as genuine gaps.
        self.assertEqual(
            set(artist_plan.unmatched_local_tracks),
            {"Wishmaster (Live)", "Amaranth", "Amaranth (Demo)",
             *[f"deepcut{i}" for i in range(6, 13)]},
        )
        item_ids = artist_plan.playlist_plan.planned_item_ids
        self.assertNotIn("2", item_ids)
        self.assertIn("3", item_ids)
        self.assertIn("5", item_ids)

    def test_dedup_keeps_most_played_copy_with_personalization(self) -> None:
        """Option 1: with personalization the kept copy is the most-played one."""

        class PersonalizedSettings(SettingsStub):
            personalization_weight = 0.6

        class JellyfinStub(TaggingStub):
            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(id="low", name="Nemo", path="/music/low.flac",
                                  play_count=2),
                    JellyfinTrack(id="high", name="Nemo", path="/music/high.flac",
                                  play_count=99),
                ] + [
                    JellyfinTrack(id=str(i), name=f"song{i}", path=f"/music/{i}.flac")
                    for i in range(1, 12)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "playlist-new"

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [ProviderTrack(title="song1", rank=1)]
        planner = Planner(PersonalizedSettings(), jellyfin=JellyfinStub(), provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())
        artist = JellyfinArtist(id="a1", name="Nightwish")

        artist_plan = planner._plan_for_artist(user, artist, existing_playlists={})

        item_ids = artist_plan.playlist_plan.planned_item_ids
        self.assertIn("high", item_ids)
        self.assertNotIn("low", item_ids)
        self.assertEqual(artist_plan.duplicate_local_tracks, ["Nemo"])

    def test_personalization_reorders_playlist_by_user_play_count(self) -> None:
        """A heavily played track is promoted above its Last.fm rank."""

        class PersonalizedSettings(SettingsStub):
            personalization_weight = 0.6

        class JellyfinStub(TaggingStub):
            def get_artists(self, user_id):
                return [JellyfinArtist(id="a1", name="Powerwolf")]

            def get_playlists_for_user(self, user_id):
                return []

            def get_tracks_for_artist(self, user_id, artist):
                # song11 is the Last.fm bottom track but the only one the user plays.
                return [
                    JellyfinTrack(
                        id=str(index),
                        name=f"song{index}",
                        path=f"/music/song{index}.flac",
                        play_count=100 if index == 11 else 0,
                    )
                    for index in range(1, 12)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return "playlist-new"

        provider = MagicMock()
        provider.name = "lastfm"
        provider.get_top_tracks.return_value = [
            ProviderTrack(title=f"song{index}", rank=index) for index in range(1, 12)
        ]
        planner = Planner(PersonalizedSettings(), jellyfin=JellyfinStub(), provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())
        artist = JellyfinArtist(id="a1", name="Powerwolf")

        artist_plan = planner._plan_for_artist(user, artist, existing_playlists={})

        self.assertEqual(artist_plan.matched_tracks[0].jellyfin_item_id, "11")
        self.assertEqual(artist_plan.playlist_plan.planned_item_ids[0], "11")


class ConcurrencyPlannerTests(unittest.TestCase):
    """Stage 2: concurrent per-artist planning must match the sequential run."""

    @staticmethod
    def _run(run_concurrency: int, artist_names: list[str], failing=()) -> object:
        settings_cls = type(
            "ConcSettings", (SettingsStub,), {"run_concurrency": run_concurrency}
        )

        class JellyfinStub(TaggingStub):
            def get_artists(self, user_id):
                return [
                    JellyfinArtist(id=f"a{index}", name=name)
                    for index, name in enumerate(artist_names)
                ]

            def get_playlists_for_user(self, user_id):
                return []

            def get_tracks_for_artist(self, user_id, artist):
                return [
                    JellyfinTrack(
                        id=f"{artist.id}-{i}",
                        name=f"song{i}",
                        path=f"/music/{artist.id}/{i}.flac",
                    )
                    for i in range(1, 13)
                ]

            def create_playlist(self, user_id, playlist_name, item_ids):
                return f"created-{playlist_name}"

            def delete_playlist(self, playlist_id):
                pass

        class ProviderStub:
            name = "lastfm"

            def get_top_tracks(self, artist_name):
                if artist_name in failing:
                    raise RuntimeError(f"provider down for {artist_name}")
                return [ProviderTrack(title="song1", rank=1)]

        planner = Planner(settings_cls(), jellyfin=JellyfinStub(), provider=ProviderStub())
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())
        return planner._plan_for_user(user)

    @staticmethod
    def _plan_key(user_plan) -> tuple:
        return (
            [plan.artist for plan in user_plan.artists],
            user_plan.eligible_artist_count,
            user_plan.planned_playlist_count,
            user_plan.failed_artist_count,
            user_plan.orphan_deleted_count,
        )

    def test_concurrency_does_not_change_the_result(self) -> None:
        artist_names = [f"Artist{i:02d}" for i in range(12)]
        baseline = None
        # A single concurrent pass proves little; repeat to shake out races.
        for _ in range(20):
            sequential = self._plan_key(self._run(1, artist_names))
            concurrent = self._plan_key(self._run(4, artist_names))
            self.assertEqual(sequential, concurrent)
            if baseline is None:
                baseline = sequential
            self.assertEqual(concurrent, baseline)

    def test_partial_failure_isolates_and_preserves_artist_order(self) -> None:
        artist_names = [f"Artist{i:02d}" for i in range(8)]

        user_plan = self._run(4, artist_names, failing={"Artist03"})

        self.assertEqual([plan.artist for plan in user_plan.artists], artist_names)
        self.assertEqual(user_plan.failed_artist_count, 1)
        self.assertEqual(user_plan.planned_playlist_count, 7)
        failed = next(plan for plan in user_plan.artists if plan.artist == "Artist03")
        self.assertIsNotNone(failed.error)

    def test_concurrent_cache_misses_share_result_without_lock_held_during_io(self) -> None:
        barrier = threading.Barrier(2, timeout=5)

        class BarrierProvider:
            name = "lastfm"

            def __init__(self) -> None:
                self.call_count = 0
                self._lock = threading.Lock()

            def get_top_tracks(self, artist_name):
                with self._lock:
                    self.call_count += 1
                # If _cache_lock were held across the network call, the second
                # thread could not reach here and the barrier would time out.
                barrier.wait()
                return [ProviderTrack(title="song1", rank=1)]

        provider = BarrierProvider()
        planner = Planner(SettingsStub(), jellyfin=None, provider=provider)
        results: dict[int, object] = {}
        errors: dict[int, BaseException] = {}

        def worker(index: int) -> None:
            try:
                results[index] = planner._get_provider_tracks("Powerwolf")
            except BaseException as exc:  # noqa: BLE001 - surfaced via the errors dict
                errors[index] = exc

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)

        self.assertEqual(errors, {})
        self.assertEqual(provider.call_count, 2)
        # setdefault: the first writer wins and both callers adopt that value.
        self.assertIs(results[0], results[1])

    def test_collision_loser_existing_playlist_is_protected_from_orphan_deletion(self) -> None:
        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.deleted: list[str] = []

            def get_artists(self, user_id):
                return [
                    JellyfinArtist(id="a1", name="A/B"),
                    JellyfinArtist(id="a2", name="A_B"),
                ]

            def get_playlists_for_user(self, user_id):
                return [JellyfinPlaylist(id="p1", name="Top Songs - A_B")]

            def get_tracks_for_artist(self, user_id, artist):
                # Below the eligibility threshold: the collision winner plans
                # no playlist, so only protected_names can save the existing one.
                return [
                    JellyfinTrack(id=f"{artist.id}-{i}", name=f"s{i}", path=f"/music/{i}.flac")
                    for i in range(5)
                ]

            def delete_playlist(self, playlist_id):
                self.deleted.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        jellyfin = JellyfinStub()
        planner = Planner(SettingsStub(), jellyfin=jellyfin, provider=provider)
        user = JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())

        user_plan = planner._plan_for_user(user)

        self.assertEqual(user_plan.planned_playlist_count, 0)
        self.assertEqual(user_plan.orphan_deleted_count, 0)
        self.assertEqual(jellyfin.deleted, [])
        loser = next(plan for plan in user_plan.artists if plan.artist == "A_B")
        self.assertTrue(any("collision" in note for note in loser.notes))


def _track_ids(prefix: str, count: int = 11) -> list[str]:
    return [f"{prefix}{i}" for i in range(count)]


class LibraryJellyfin:
    """Stateful Jellyfin fake: playlists persist across runs as on the server.

    ``library`` maps artist name -> track ids. Two names sharing one list model
    a band that Jellyfin holds as two artists.
    """

    def __init__(self, library, playlists=(), failing=()) -> None:
        self.library = library
        self.playlists = {playlist.id: playlist for playlist in playlists}
        self.items: dict[str, list[str]] = {}
        self.failing = set(failing)
        self.created: list[str] = []
        self.deleted: list[str] = []
        self._ids = itertools.count(1)

    def get_users(self):
        return [JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy())]

    def get_artists(self, user_id):
        return [JellyfinArtist(id=f"a{i}", name=name) for i, name in enumerate(self.library)]

    def get_playlists_for_user(self, user_id):
        return list(self.playlists.values())

    def get_tracks_for_artist(self, user_id, artist):
        if artist.name in self.failing:
            raise RuntimeError(f"jellyfin down for {artist.name}")
        return [
            JellyfinTrack(id=track_id, name=track_id, path=f"/music/{track_id}.flac")
            for track_id in self.library[artist.name]
        ]

    def create_playlist(self, user_id, playlist_name, item_ids):
        playlist_id = f"p{next(self._ids)}"
        self.playlists[playlist_id] = JellyfinPlaylist(id=playlist_id, name=playlist_name)
        self.items[playlist_id] = list(item_ids)
        self.created.append(playlist_name)
        return playlist_id

    def add_managed_tag(self, user_id, playlist_id, tag):
        self.playlists[playlist_id].tags.append(tag)

    def delete_playlist(self, playlist_id):
        del self.playlists[playlist_id]
        self.items.pop(playlist_id, None)
        self.deleted.append(playlist_id)

    def snapshot(self) -> list[tuple]:
        """Playlists as (name, tags, ordered item ids), independent of ids."""
        return sorted(
            (p.name, tuple(p.tags), tuple(self.items.get(p.id, ())))
            for p in self.playlists.values()
        )


class LibraryProvider:
    """Last.fm stub: an artist's top tracks are its first five, reversed."""

    name = "lastfm"

    def __init__(self, library) -> None:
        self.library = library

    def get_top_tracks(self, artist_name):
        titles = list(reversed(self.library[artist_name][:5]))
        return [ProviderTrack(title=title, rank=rank) for rank, title in enumerate(titles, 1)]


def _settings(base=BareNameSettings, run_concurrency: int = 1):
    return type("DuplicateSettings", (base,), {"run_concurrency": run_concurrency})()


def _plan_user(jellyfin: LibraryJellyfin, settings=None):
    """Plan the fake's only user, with Last.fm answering from the same library."""
    planner = Planner(
        settings or _settings(), jellyfin=jellyfin, provider=LibraryProvider(jellyfin.library)
    )
    return planner._plan_for_user(jellyfin.get_users()[0])


class DuplicateArtistTests(unittest.TestCase):
    """One band held by Jellyfin as two artists: same name up to case and
    punctuation, identical tracks."""

    def test_duplicate_artists_share_one_playlist(self) -> None:
        blackmore, hammerfall, motley = _track_ids("bn"), _track_ids("hf"), _track_ids("mc")
        library = {
            "Blackmore's Night": blackmore,
            "Blackmore’s Night": blackmore,  # typographic apostrophe
            "HAMMERFALL": hammerfall,
            "HammerFall": hammerfall,
            "Mötley Crüe": motley,  # composed (NFC)
            "Mötley Crüe": motley,  # decomposed (NFD)
        }
        winners = ["Blackmore's Night", "HAMMERFALL", "Mötley Crüe"]
        for base, prefix, tags in (
            (BareNameSettings, "", ["topsongs"]),
            (SettingsStub, "Top Songs - ", []),
        ):
            with self.subTest(prefix=prefix):
                jellyfin = LibraryJellyfin(
                    library,
                    playlists=[
                        JellyfinPlaylist(id="old1", name=f"{prefix}Blackmore's Night", tags=tags),
                        JellyfinPlaylist(id="old2", name=f"{prefix}Blackmore’s Night", tags=tags),
                    ],
                )
                user_plan = _plan_user(jellyfin, _settings(base))

                self.assertEqual(sorted(jellyfin.created), sorted(prefix + w for w in winners))
                # old1 is replaced by the winner; old2, the duplicate's, is an orphan.
                self.assertEqual(sorted(jellyfin.deleted), ["old1", "old2"])
                self.assertEqual(user_plan.orphan_deleted_count, 1)
                self.assertEqual(user_plan.eligible_artist_count, 3)
                for plan in user_plan.artists:
                    if plan.artist in winners:
                        continue
                    self.assertIsNone(plan.playlist_plan)
                    self.assertFalse(plan.eligible)
                    self.assertTrue(any("Duplicate of" in n for n in plan.notes))

    def test_name_and_tracks_must_both_match(self) -> None:
        """Look-alike names with other tracks, a diacritic variant, two artists
        sharing only a duet album and two all-punctuation names each keep
        their own playlist."""
        duet = _track_ids("duet")
        library = {
            "Blackmore's Night": _track_ids("bn"),
            "Blackmore’s Night": _track_ids("bn2"),  # same name, other tracks
            "Motörhead": _track_ids("mh"),
            "Motorhead": _track_ids("mh"),  # same tracks, name differs by a letter
            "Jay-Z": duet,
            "Kanye West": duet,  # same tracks, different name
            "!!!": _track_ids("pn"),
            "+++": _track_ids("pn"),  # nothing left to compare once punctuation goes
        }
        jellyfin = LibraryJellyfin(library)

        with self.assertNoLogs("topsongs.planner", level="WARNING"):
            user_plan = _plan_user(jellyfin)

        self.assertEqual(sorted(jellyfin.created), sorted(library))
        self.assertEqual(user_plan.planned_playlist_count, 8)

    def test_duplicate_check_ignores_ineligible_artists(self) -> None:
        """Below the track threshold nothing gets a playlist, so no duplicate
        warning either (keeps the run log free of one-track artists)."""
        library = {"Destiny's Child": ["dc0"], "Destiny’s Child": ["dc0"]}
        jellyfin = LibraryJellyfin(library)

        with self.assertNoLogs("topsongs.planner", level="WARNING"):
            user_plan = _plan_user(jellyfin)

        for plan in user_plan.artists:
            self.assertFalse(any("Duplicate of" in n for n in plan.notes))

    def test_first_artist_in_order_wins_under_concurrency(self) -> None:
        """The first artist's fetch finishes last, yet it still wins."""
        tracks = _track_ids("bn")
        library = {"Blackmore's Night": tracks, "Blackmore’s Night": tracks}
        jellyfin = LibraryJellyfin(library)
        second_fetched = threading.Event()
        fetch = jellyfin.get_tracks_for_artist

        def first_fetch_finishes_last(user_id, artist):
            if artist.name == "Blackmore's Night":
                self.assertTrue(second_fetched.wait(timeout=5))
                return fetch(user_id, artist)
            tracks = fetch(user_id, artist)
            second_fetched.set()
            return tracks

        jellyfin.get_tracks_for_artist = first_fetch_finishes_last

        user_plan = _plan_user(jellyfin, _settings(run_concurrency=2))

        self.assertEqual(user_plan.failed_artist_count, 0)
        self.assertEqual(jellyfin.created, ["Blackmore's Night"])

    def test_track_fetch_failure_is_isolated_and_keeps_its_playlist(self) -> None:
        library = {"Alpha": _track_ids("al"), "Beta": _track_ids("be")}
        jellyfin = LibraryJellyfin(
            library,
            playlists=[JellyfinPlaylist(id="old-alpha", name="Alpha", tags=["topsongs"])],
            failing={"Alpha"},
        )

        user_plan = _plan_user(jellyfin, _settings(run_concurrency=2))

        self.assertEqual(user_plan.failed_artist_count, 1)
        self.assertEqual(user_plan.artists[0].error, "jellyfin down for Alpha")
        self.assertEqual(jellyfin.created, ["Beta"])
        self.assertEqual(jellyfin.deleted, [])  # the failed artist's playlist survives

    def test_repeated_runs_give_identical_results(self) -> None:
        """Unchanged Jellyfin and Last.fm data: every run after the first leaves
        the same playlists with the same tracks in the same order, whatever the
        concurrency, and the first run's duplicate cleanup sticks."""
        blackmore = _track_ids("bn")
        library = {
            "A/B": _track_ids("ab"),
            "A_B": _track_ids("a_b"),  # same playlist name as A/B, other tracks
            "Blackmore's Night": blackmore,
            "Blackmore’s Night": blackmore,
            "Nightwish": _track_ids("nw", 20),
            "Sabaton": _track_ids("sb", 15),
        }
        jellyfin = LibraryJellyfin(
            library,
            playlists=[
                JellyfinPlaylist(id="old1", name="Blackmore's Night", tags=["topsongs"]),
                JellyfinPlaylist(id="old2", name="Blackmore’s Night", tags=["topsongs"]),
            ],
        )
        provider = LibraryProvider(library)

        snapshots, reports = [], []
        for concurrency in (1, 4, 1, 4):
            planner = Planner(_settings(run_concurrency=concurrency), jellyfin, provider)
            reports.append(planner.run())
            snapshots.append(jellyfin.snapshot())

        names = [name for name, _, _ in snapshots[0]]
        self.assertEqual(names, ["A_B", "Blackmore's Night", "Nightwish", "Sabaton"])
        for snapshot in snapshots[1:]:
            self.assertEqual(snapshot, snapshots[0])
        self.assertEqual(reports[0].orphan_deleted_count, 1)
        for report in reports[1:]:
            self.assertEqual(report.created_playlist_count, 0)
            self.assertEqual(report.replaced_playlist_count, 4)
            self.assertEqual(report.orphan_deleted_count, 0)


class LivePlaylistSafetyTests(unittest.TestCase):
    """The nightly run must never treat on-request live playlists as its own."""

    def _run(self, settings) -> list[str]:
        class JellyfinStub(TaggingStub):
            def __init__(self) -> None:
                self.deleted: list[str] = []

            def get_artists(self, user_id):
                return []

            def get_playlists_for_user(self, user_id):
                return [
                    JellyfinPlaylist(id="old", name="Top Songs - Gone", tags=["topsongs"]),
                    JellyfinPlaylist(id="gone", name="Gone", tags=["topsongs"]),
                    JellyfinPlaylist(
                        id="live",
                        name="Live - Metallica - Mix aus 5 Konzerten",
                        tags=["topsongs-live"],
                    ),
                    # A live playlist whose name looks like a nightly one.
                    JellyfinPlaylist(
                        id="live-2", name="Top Songs - Metallica live", tags=["topsongs-live"]
                    ),
                ]

            def delete_playlist(self, playlist_id):
                self.deleted.append(playlist_id)

        provider = MagicMock()
        provider.name = "lastfm"
        jellyfin = JellyfinStub()
        planner = Planner(settings, jellyfin=jellyfin, provider=provider)
        planner._plan_for_user(JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy()))
        return jellyfin.deleted

    def test_keeps_live_playlists_whatever_their_name(self) -> None:
        self.assertEqual(sorted(self._run(SettingsStub())), ["gone", "old"])


class LegacyAdoptionTests(unittest.TestCase):
    """Playlists of a topsongs from before tags are taken over once, by prefix."""

    def _plan(self, settings, playlists) -> list[tuple[str, str]]:
        tagged: list[tuple[str, str]] = []

        class JellyfinStub:
            def get_artists(self, user_id):
                return []

            def get_playlists_for_user(self, user_id):
                return playlists

            def add_managed_tag(self, user_id, playlist_id, tag):
                tagged.append((playlist_id, tag))

            def delete_playlist(self, playlist_id):
                pass

        provider = MagicMock()
        provider.name = "lastfm"
        planner = Planner(settings, jellyfin=JellyfinStub(), provider=provider)
        planner._plan_for_user(JellyfinUser(id="u1", name="Alice", policy=JellyfinUserPolicy()))
        return tagged

    def test_untagged_prefixed_playlists_are_tagged_when_the_user_has_none(self) -> None:
        playlists = [
            JellyfinPlaylist(id="old", name="Top Songs - Metallica"),
            JellyfinPlaylist(id="own", name="Mixtape"),
            JellyfinPlaylist(id="live", name="Top Songs - live", tags=["topsongs-live"]),
        ]

        self.assertEqual(self._plan(SettingsStub(), playlists), [("old", "topsongs")])

    def test_without_a_prefix_the_old_default_prefix_is_taken_over(self) -> None:
        playlists = [JellyfinPlaylist(id="old", name="Top Songs - Metallica")]

        self.assertEqual(self._plan(BareNameSettings(), playlists), [("old", "topsongs")])

    def test_nothing_is_taken_over_once_the_user_has_tagged_playlists(self) -> None:
        playlists = [
            JellyfinPlaylist(id="new", name="Metallica", tags=["topsongs"]),
            JellyfinPlaylist(id="own", name="Top Songs - selbst gemacht"),
        ]

        self.assertEqual(self._plan(BareNameSettings(), playlists), [])

    def test_dry_run_writes_no_tag(self) -> None:
        class DryRun(SettingsStub):
            dry_run = True

        playlists = [JellyfinPlaylist(id="old", name="Top Songs - Metallica")]

        self.assertEqual(self._plan(DryRun(), playlists), [])


if __name__ == "__main__":
    unittest.main()
