from topsongs.sanitize import MAX_PROVIDER_TRACKS, sanitize_untrusted_text


def test_sanitize_untrusted_text_removes_control_chars_and_ansi() -> None:
    value = "Hello\x1b[31m\nWorld\r\tTest"
    assert sanitize_untrusted_text(value) == "Hello World Test"


def test_sanitize_untrusted_text_limits_length() -> None:
    value = "a" * 500
    assert len(sanitize_untrusted_text(value)) == 200


def test_provider_track_limit_constant() -> None:
    assert MAX_PROVIDER_TRACKS == 200
