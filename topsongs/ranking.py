from __future__ import annotations

import math
from collections.abc import Sequence

from .models import TrackMatch

# How much a Jellyfin "favorite" (heart) adds to a track's personal score, on
# the same 0..1 scale as the normalized play count. Deliberately not an env
# knob: keeping a single PERSONALIZATION_WEIGHT dial makes the feature easy to
# reason about.
_FAVORITE_BONUS = 0.25


def rerank_matches(matches: Sequence[TrackMatch], weight: float) -> list[TrackMatch]:
    """Reorder one artist's matched tracks by blending Last.fm rank with the
    user's own listening.

    ``matches`` arrives in Last.fm rank order. Each track gets a blended score
    of two values normalized to 0..1: its Last.fm position and a personal score
    derived from the user's play count (log-scaled, so engagement matters more
    than a single binge) plus a bonus for favorites. ``weight`` (0..1) is how
    much the personal score counts; ``0.0`` returns the list unchanged.

    Play counts are normalized against the most-played track in this same list,
    so the ranking stays purely per-artist: an artist the user barely listened
    to has little personal signal and naturally keeps the Last.fm order.
    """
    ordered = list(matches)
    if weight <= 0.0 or len(ordered) < 2:
        return ordered

    last_index = len(ordered) - 1
    log_max_plays = math.log1p(max(match.play_count for match in ordered))

    def blended_score(index: int, match: TrackMatch) -> float:
        lastfm_score = 1.0 - index / last_index
        if log_max_plays > 0.0:
            play_score = math.log1p(match.play_count) / log_max_plays
        else:
            play_score = 0.0
        favorite_bonus = _FAVORITE_BONUS if match.is_favorite else 0.0
        personal_score = min(1.0, play_score + favorite_bonus)
        return (1.0 - weight) * lastfm_score + weight * personal_score

    indexed = list(enumerate(ordered))
    # sort() is stable, so tracks with an equal blended score keep their
    # original Last.fm order.
    indexed.sort(key=lambda pair: blended_score(pair[0], pair[1]), reverse=True)
    return [match for _, match in indexed]
