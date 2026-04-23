import unittest

from topsongs.jellyfin import JellyfinClient


class JellyfinClientTests(unittest.TestCase):
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

    def test_delete_playlist_uses_item_endpoint(self) -> None:
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="token")
        calls = []
        client._delete = lambda path: calls.append(path)  # type: ignore[method-assign]

        client.delete_playlist("playlist-123")

        self.assertEqual(calls, ["/Items/playlist-123"])


if __name__ == "__main__":
    unittest.main()
