import unittest

from topsongs.providers.lastfm import LastFmError, LastFmProvider, _validate_raw_response_prefix


class LastFmResponseValidationTests(unittest.TestCase):
    def test_accepts_toptracks_prefix(self) -> None:
        _validate_raw_response_prefix('{"toptracks":{"track":[]}}', "Powerwolf")

    def test_accepts_error_prefix(self) -> None:
        _validate_raw_response_prefix('{"error":29,"message":"Rate limit"}', "Powerwolf")

    def test_rejects_unexpected_prefix(self) -> None:
        with self.assertRaises(LastFmError):
            _validate_raw_response_prefix('{"foo":{"track":[]}}', "Powerwolf")

    def test_max_tracks_sets_request_limit_and_response_slice(self) -> None:
        provider = LastFmProvider(api_key="key", max_tracks=2)
        calls = []

        def fake_request(params, artist_name):
            calls.append((params, artist_name))
            return {
                "toptracks": {
                    "track": [
                        {"name": "One", "@attr": {"rank": "1"}},
                        {"name": "Two", "@attr": {"rank": "2"}},
                        {"name": "Three", "@attr": {"rank": "3"}},
                    ]
                }
            }

        provider._request_json = fake_request  # type: ignore[method-assign]

        tracks = provider.get_top_tracks("Artist")

        self.assertEqual(calls[0][0]["limit"], "2")
        self.assertEqual([track.title for track in tracks], ["One", "Two"])


if __name__ == "__main__":
    unittest.main()
