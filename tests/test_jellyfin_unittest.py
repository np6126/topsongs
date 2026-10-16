import unittest

import httpx

from topsongs.jellyfin import JellyfinClient, _is_retryable_http_error


class JellyfinClientTests(unittest.TestCase):
    def test_default_headers_use_authorization_token(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")

        self.assertEqual(client.default_headers["Authorization"], 'MediaBrowser Token="token"')
        self.assertNotIn("X-Emby-Token", client.default_headers)

    def test_create_playlist_uses_target_user_and_returns_created_id(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        calls = []
        client._post = lambda path, params: calls.append((path, params)) or {"Id": "playlist-123"}  # type: ignore[method-assign]

        playlist_id = client.create_playlist("user-123", "Top Songs - Artist", ["a", "b"])

        self.assertEqual(playlist_id, "playlist-123")
        self.assertEqual(calls[0][0], "/Playlists")
        self.assertEqual(calls[0][1]["UserId"], "user-123")
        self.assertEqual(calls[0][1]["Name"], "Top Songs - Artist")
        self.assertEqual(calls[0][1]["Ids"], "a,b")

    def test_get_users_maps_policy(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        client._get = lambda path, params: [  # type: ignore[method-assign]
            {
                "Id": "u1",
                "Name": "Admin",
                "Policy": {
                    "IsAdministrator": True,
                    "IsDisabled": False,
                    "IsHidden": True,
                    "EnableAllFolders": False,
                    "EnabledFolders": ["folder-1", "folder-2"],
                },
            }
        ]

        users = client.get_users()

        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].id, "u1")
        self.assertTrue(users[0].policy.is_administrator)
        self.assertTrue(users[0].policy.is_hidden)
        self.assertEqual(users[0].policy.enabled_folders, ["folder-1", "folder-2"])

    def test_get_playlists_for_user_maps_items(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        client._get = lambda path, params: {  # type: ignore[method-assign]
            "Items": [
                {"Id": "p1", "Name": "Top Songs - Powerwolf"},
                {"Id": "p2", "Name": "Top Songs - Blind Guardian"},
            ]
        }

        playlists = client.get_playlists_for_user("user-1")

        self.assertEqual([playlist.id for playlist in playlists], ["p1", "p2"])
        self.assertEqual(playlists[0].name, "Top Songs - Powerwolf")

    def test_get_artists_uses_album_artists_endpoint_with_user_id(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        calls = []
        client._get = lambda path, params: calls.append((path, params)) or {  # type: ignore[method-assign]
            "Items": [
                {"Id": "a1", "Name": "AC/DC", "SortName": "ac/dc"},
                {"Id": "a2", "Name": "Powerwolf", "SortName": "powerwolf"},
            ]
        }

        artists = client.get_artists("user-1")

        self.assertEqual(calls[0][0], "/Artists/AlbumArtists")
        self.assertEqual(calls[0][1]["UserId"], "user-1")
        self.assertEqual(len(artists), 2)
        self.assertEqual(artists[0].name, "AC/DC")

    def test_get_tracks_for_artist_requests_and_maps_runtime_ticks(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        calls = []
        client._get = lambda path, params: calls.append((path, params)) or {  # type: ignore[method-assign]
            "Items": [
                {
                    "Id": "t1",
                    "Name": "Army of the Night",
                    "RunTimeTicks": 59 * 10_000_000,
                }
            ]
        }

        tracks = client.get_tracks_for_artist("user-1", type("Artist", (), {"id": "a1"})())

        self.assertIn("RunTimeTicks", calls[0][1]["Fields"])
        self.assertEqual(tracks[0].runtime_ticks, 59 * 10_000_000)

    def test_get_tracks_for_artist_parses_user_play_data(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        calls = []
        client._get = lambda path, params: calls.append((path, params)) or {  # type: ignore[method-assign]
            "Items": [
                {
                    "Id": "t1",
                    "Name": "Resist and Bite",
                    "ProductionYear": 2014,
                    "UserData": {"PlayCount": 12, "IsFavorite": True},
                },
                {"Id": "t2", "Name": "Coleus Sanctus"},
            ]
        }

        tracks = client.get_tracks_for_artist("user-1", type("Artist", (), {"id": "a1"})())

        self.assertIn("UserData", calls[0][1]["Fields"])
        self.assertEqual(tracks[0].play_count, 12)
        self.assertTrue(tracks[0].is_favorite)
        self.assertEqual(tracks[0].year, 2014)
        self.assertEqual(tracks[1].play_count, 0)
        self.assertFalse(tracks[1].is_favorite)
        self.assertIsNone(tracks[1].year)

    def test_delete_playlist_uses_item_endpoint(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        calls = []
        client._delete = lambda path: calls.append(path)  # type: ignore[method-assign]

        client.delete_playlist("playlist-123")

        self.assertEqual(calls, ["/Items/playlist-123"])

    def test_rename_playlist_reads_dto_and_posts_name_only(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        gets = []
        posts = []
        client._get = lambda path, params: gets.append((path, params)) or {  # type: ignore[method-assign]
            "Id": "p1",
            "Name": "Favorites",
            "Overview": "keep me",
        }
        client._post_json = lambda path, body: posts.append((path, body))  # type: ignore[method-assign]

        client.rename_playlist("user-1", "p1", "_Favorites")

        self.assertEqual(gets[0][0], "/Users/user-1/Items/p1")
        self.assertEqual(posts[0][0], "/Items/p1")
        self.assertEqual(posts[0][1]["Name"], "_Favorites")
        # Other DTO fields are posted back unchanged.
        self.assertEqual(posts[0][1]["Overview"], "keep me")

    def test_get_playlists_for_user_omits_media_types_when_none(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        calls = []
        client._get = lambda path, params: calls.append((path, params)) or {  # type: ignore[method-assign]
            "Items": [{"Id": "p1", "Name": "Favorites"}]
        }

        client.get_playlists_for_user("user-1", media_types=None)

        self.assertNotIn("MediaTypes", calls[0][1])

    def test_add_managed_tag_reads_dto_appends_tag_and_posts(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        gets = []
        posts = []
        client._get = lambda path, params: gets.append((path, params)) or {  # type: ignore[method-assign]
            "Id": "p1",
            "Name": "AC_DC",
            "Tags": ["existing"],
        }
        client._post_json = lambda path, body: posts.append((path, body))  # type: ignore[method-assign]

        client.add_managed_tag("user-1", "p1", "topsongs")

        self.assertEqual(gets[0][0], "/Users/user-1/Items/p1")
        self.assertEqual(posts[0][0], "/Items/p1")
        # The existing tag is preserved; the managed tag is appended.
        self.assertEqual(posts[0][1]["Tags"], ["existing", "topsongs"])

    def test_add_managed_tag_is_noop_when_tag_already_present(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        posts = []
        client._get = lambda path, params: {  # type: ignore[method-assign]
            "Id": "p1",
            "Name": "AC_DC",
            "Tags": ["topsongs"],
        }
        client._post_json = lambda path, body: posts.append((path, body))  # type: ignore[method-assign]

        client.add_managed_tag("user-1", "p1", "topsongs")

        self.assertEqual(posts, [])

    def test_get_playlists_for_user_requests_tags_and_maps_them(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        calls = []
        client._get = lambda path, params: calls.append((path, params)) or {  # type: ignore[method-assign]
            "Items": [
                {"Id": "p1", "Name": "AC_DC", "Tags": ["topsongs"]},
                {"Id": "p2", "Name": "Favorites"},
            ]
        }

        playlists = client.get_playlists_for_user("user-1")

        self.assertEqual(calls[0][1]["Fields"], "Tags")
        self.assertEqual(playlists[0].tags, ["topsongs"])
        self.assertEqual(playlists[1].tags, [])

    def test_close_closes_pooled_client(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")

        client.close()

        self.assertTrue(client._client.is_closed)

    def test_context_manager_closes_pooled_client(self) -> None:
        with JellyfinClient(base_url="http://jellyfin:8096", api_key="token") as client:
            self.assertFalse(client._client.is_closed)

        self.assertTrue(client._client.is_closed)

    def test_remote_protocol_error_is_retryable(self) -> None:
        self.assertTrue(_is_retryable_http_error(httpx.RemoteProtocolError("peer closed")))


if __name__ == "__main__":
    unittest.main()
