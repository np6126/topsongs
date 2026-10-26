from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import timedelta

from .models import PlaybackEvent

# A playback that ends sooner is a skip; 30 s is Last.fm's minimum for a scrobble.
SKIP_TIME = timedelta(seconds=30)


def count_skips(events: Iterable[PlaybackEvent]) -> Counter[tuple[str, str]]:
    """Count skipped playbacks per (user id, item id).

    Jellyfin raises PlayCount when playback starts, so each skip counts as a
    play. A start ends at the same user's next start or at the next stop of the
    same item, whichever comes first: some clients (Jellyfin for Android TV)
    report no stop between tracks. Grouping by user instead of by device is
    accurate enough, because a user rarely plays on two devices at once. A start
    with nothing after it (still playing) is not a skip.
    """
    skips: Counter[tuple[str, str]] = Counter()
    open_starts: dict[str, PlaybackEvent] = {}
    for event in sorted(events, key=lambda event: event.at):
        start = open_starts.get(event.user_id)
        if start is not None and (event.started or event.item_id == start.item_id):
            if event.at - start.at < SKIP_TIME:
                skips[(start.user_id, start.item_id)] += 1
            del open_starts[event.user_id]
        if event.started:
            open_starts[event.user_id] = event
    return skips
