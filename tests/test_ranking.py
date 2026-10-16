import pytest

from topsongs.models import TrackMatch
from topsongs.ranking import rerank_matches


def _match(
    item_id: str,
    play_count: int = 0,
    is_favorite: bool = False,
    year: int | None = None,
) -> TrackMatch:
    return TrackMatch(
        provider_title=item_id,
        jellyfin_item_id=item_id,
        jellyfin_title=item_id,
        match_type="exact",
        play_count=play_count,
        is_favorite=is_favorite,
        year=year,
    )


def _ids(matches: list[TrackMatch]) -> list[str]:
    return [match.jellyfin_item_id for match in matches]


def test_weight_zero_keeps_lastfm_order() -> None:
    matches = [_match("a", play_count=0), _match("b", play_count=100)]

    assert _ids(rerank_matches(matches, weight=0.0)) == ["a", "b"]


def test_single_match_is_returned_unchanged() -> None:
    matches = [_match("a", play_count=5)]

    assert _ids(rerank_matches(matches, weight=1.0)) == ["a"]


def test_empty_list_is_returned_unchanged() -> None:
    assert rerank_matches([], weight=0.6) == []


def test_heavily_played_low_ranked_track_moves_to_top() -> None:
    # "a" is the Last.fm #1, "e" is last; the user only ever plays "e".
    matches = [
        _match("a"),
        _match("b"),
        _match("c"),
        _match("d"),
        _match("e", play_count=100),
    ]

    assert _ids(rerank_matches(matches, weight=0.6))[0] == "e"


def test_no_plays_anywhere_falls_back_to_lastfm_order() -> None:
    matches = [_match("a"), _match("b"), _match("c")]

    assert _ids(rerank_matches(matches, weight=1.0)) == ["a", "b", "c"]


def test_favorite_bonus_lifts_an_otherwise_unplayed_track() -> None:
    # No plays at all, but "c" is a favorite, so it should move ahead.
    matches = [_match("a"), _match("b"), _match("c", is_favorite=True)]

    assert _ids(rerank_matches(matches, weight=1.0))[0] == "c"


def test_equal_personal_scores_keep_lastfm_order() -> None:
    # Identical play counts and weight=1.0 -> equal blended scores; the stable
    # sort must preserve the incoming Last.fm order.
    matches = [
        _match("a", play_count=5),
        _match("b", play_count=5),
        _match("c", play_count=5),
    ]

    assert _ids(rerank_matches(matches, weight=1.0)) == ["a", "b", "c"]


def test_modest_plays_do_not_overturn_a_top_hit() -> None:
    # The Last.fm #1 is also the most-played track; a mid-list track with only
    # a couple of plays should not leapfrog it at a moderate weight.
    matches = [
        _match("hit", play_count=8),
        _match("b"),
        _match("c"),
        _match("deep_cut", play_count=2),
        _match("e"),
    ]

    assert _ids(rerank_matches(matches, weight=0.6))[0] == "hit"


def test_recency_bonus_lifts_a_new_release_even_without_personalization() -> None:
    # Last.fm scores 1, .75, .5, .25, 0; the bonus lifts "new" from 0 to .3,
    # past "d" but not past "c".
    matches = [_match("a"), _match("b"), _match("c"), _match("d"), _match("new", year=2026)]

    reranked = rerank_matches(matches, weight=0.0, recency_bonus=0.3, current_year=2026)

    assert _ids(reranked) == ["a", "b", "c", "new", "d"]


@pytest.mark.parametrize(
    ("year", "lifted"),
    [
        (2027, True),  # tagged ahead of time: treated as this year's release
        (2026, True),  # full bonus .9
        (2025, True),  # 2/3 of it: .6
        (2024, False),  # 1/3 of it: .3
        (2023, False),  # faded out
        (None, False),  # no year tag
    ],
)
def test_recency_bonus_fades_over_three_years(year: int | None, lifted: bool) -> None:
    # Last.fm scores 1, .5, 0: "new" needs more than .5 to pass "b".
    matches = [_match("a"), _match("b"), _match("new", year=year)]

    reranked = rerank_matches(matches, weight=0.0, recency_bonus=0.9, current_year=2026)

    assert _ids(reranked) == (["a", "new", "b"] if lifted else ["a", "b", "new"])
