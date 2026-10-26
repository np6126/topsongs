from datetime import datetime, timedelta, timezone
from functools import partial

from topsongs.listening import count_skips
from topsongs.models import PlaybackEvent

_T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _event(started: bool, item_id: str, second: int, user_id: str = "u1") -> PlaybackEvent:
    return PlaybackEvent(
        user_id=user_id, item_id=item_id, started=started, at=_T0 + timedelta(seconds=second)
    )


_start = partial(_event, True)
_stop = partial(_event, False)


def test_stop_within_30_seconds_is_a_skip() -> None:
    events = [_start("a", 0), _stop("a", 29), _start("b", 30), _stop("b", 60)]

    assert count_skips(events) == {("u1", "a"): 1}


def test_next_start_ends_a_playback_without_stop() -> None:
    # Jellyfin for Android TV reports no stop between tracks.
    events = [_start("a", 0), _start("b", 5), _start("c", 200)]

    assert count_skips(events) == {("u1", "a"): 1}


def test_restarting_the_same_track_skips_the_first_start() -> None:
    events = [_start("a", 0), _start("a", 3), _stop("a", 240)]

    assert count_skips(events) == {("u1", "a"): 1}


def test_stray_and_repeated_stops_do_not_end_a_playback() -> None:
    # Jellyfin for Android sends a second stop with position 0 right after the
    # first; a late stop of the previous track must not end the current one.
    events = [
        _start("a", 0),
        _stop("a", 200),
        _stop("a", 200),
        _start("b", 201),
        _stop("a", 202),
        _stop("b", 400),
    ]

    assert count_skips(events) == {}


def test_users_are_tracked_separately() -> None:
    events = [_start("a", 0, "u1"), _start("b", 5, "u2"), _stop("a", 180, "u1")]

    assert count_skips(events) == {}


def test_input_order_does_not_matter() -> None:
    # The activity log lists the newest entry first.
    events = [_stop("a", 10), _start("a", 0)]

    assert count_skips(events) == {("u1", "a"): 1}
