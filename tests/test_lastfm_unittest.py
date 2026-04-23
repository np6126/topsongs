import unittest

from topsongs.providers.lastfm import LastFmError, _validate_raw_response_prefix


class LastFmResponseValidationTests(unittest.TestCase):
    def test_accepts_toptracks_prefix(self) -> None:
        _validate_raw_response_prefix('{"toptracks":{"track":[]}}', "Powerwolf")

    def test_accepts_error_prefix(self) -> None:
        _validate_raw_response_prefix('{"error":29,"message":"Rate limit"}', "Powerwolf")

    def test_rejects_unexpected_prefix(self) -> None:
        with self.assertRaises(LastFmError):
            _validate_raw_response_prefix('{"foo":{"track":[]}}', "Powerwolf")


if __name__ == "__main__":
    unittest.main()
