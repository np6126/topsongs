from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from .models import TrackMatch

# How much a Jellyfin "favorite" (heart) adds to a track's personal score, on
# the same 0..1 scale as the normalized play count. Deliberately not an env
# knob: keeping a single PERSONALIZATION_WEIGHT dial for personal listening
# makes the feature easy to reason about.
_FAVORITE_BONUS = 0.25

# Calendar years over which the recency bonus fades out: a release from this
# year gets the full bonus, one from last year 2/3, two years ago 1/3, and
# anything older none.
_RECENCY_DECAY_YEARS = 3


def rerank_matches(
    matches: Sequence[TrackMatch],
    weight: float,
    recency_bonus: float = 0.0,
    current_year: int | None = None,
) -> list[TrackMatch]:
    """Reorder one artist's matched tracks by blending Last.fm rank with the
    user's own listening, plus a bonus for recent releases.

    ``matches`` arrives in Last.fm rank order. Each track gets a blended score
    of two values normalized to 0..1: its Last.fm position and a personal score
    derived from the user's play count (log-scaled, so engagement matters more
    than a single binge) plus a bonus for favorites. ``weight`` (0..1) is how
    much the personal score counts.

    Play counts are normalized against the most-played track in this same list,
    so the ranking stays purely per-artist: an artist the user barely listened
    to has little personal signal and naturally keeps the Last.fm order.

    ``recency_bonus`` is added in full for a track released in ``current_year``
    (default: this year) and fades out over ``_RECENCY_DECAY_YEARS``; tracks
    without a year get none.
    """
    ordered = list(matches)
    # No shortcut for weight and recency_bonus both 0.0: the score is then the
    # Last.fm position alone, so the stable sort returns the list unchanged.
    if len(ordered) < 2:
        return ordered

    if current_year is None:
        current_year = date.today().year
    last_index = len(ordered) - 1
    log_max_plays = math.log1p(max(match.play_count for match in ordered))

    def recency_score(match: TrackMatch) -> float:
        if match.year is None:
            return 0.0
        age = max(0, current_year - match.year)
        return max(0.0, 1.0 - age / _RECENCY_DECAY_YEARS)

    def blended_score(index: int, match: TrackMatch) -> float:
        lastfm_score = 1.0 - index / last_index
        if log_max_plays > 0.0:
            play_score = math.log1p(match.play_count) / log_max_plays
        else:
            play_score = 0.0
        favorite_bonus = _FAVORITE_BONUS if match.is_favorite else 0.0
        personal_score = min(1.0, play_score + favorite_bonus)
        return (
            (1.0 - weight) * lastfm_score
            + weight * personal_score
            + recency_bonus * recency_score(match)
        )

    indexed = list(enumerate(ordered))
    # sort() is stable, so tracks with an equal blended score keep their
    # original Last.fm order.
    indexed.sort(key=lambda pair: blended_score(pair[0], pair[1]), reverse=True)
    return [match for _, match in indexed]
