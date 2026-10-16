from topsongs.matcher import match_tracks
from topsongs.models import JellyfinTrack, ProviderTrack


def test_match_exact_and_normalized() -> None:
    provider_tracks = [
        ProviderTrack(title="Army of the Night", rank=1),
        ProviderTrack(title="We Drink Your Blood - Remastered 2018", rank=2),
    ]
    local_tracks = [
        JellyfinTrack(id="1", name="Army of the Night", album="Blessed & Possessed", year=2015),
        JellyfinTrack(id="2", name="We Drink Your Blood", album="Preachers of the Night"),
    ]

    matches, unmatched_local = match_tracks(provider_tracks, local_tracks)

    assert len(matches) == 2
    assert not unmatched_local
    assert matches[0].match_type == "exact"
    assert matches[0].year == 2015
    assert matches[1].match_type == "normalized"


def test_studio_wins_over_live_when_provider_casing_differs() -> None:
    # Last.fm returns "Of The" title case; the library has "of the". A
    # case-sensitive exact miss must not let the live edition (listed first by
    # Jellyfin) steal the studio track's rank via the normalized tier.
    provider_tracks = [ProviderTrack(title="Kings Of The Carnival Creation", rank=1)]
    local_tracks = [
        JellyfinTrack(id="live", name="Kings of the Carnival Creation (Live in Oslo)"),
        JellyfinTrack(id="studio", name="Kings of the Carnival Creation"),
    ]

    matches, unmatched_local = match_tracks(provider_tracks, local_tracks)

    assert len(matches) == 1
    assert matches[0].jellyfin_item_id == "studio"
    assert matches[0].match_type == "exact"
    assert unmatched_local == ["Kings of the Carnival Creation (Live in Oslo)"]


def test_lone_live_version_still_matches_studio_rank() -> None:
    # With no studio take owned, a lone live edition still matches the
    # provider's studio-ranked title via normalization.
    provider_tracks = [ProviderTrack(title="Kings Of The Carnival Creation", rank=1)]
    local_tracks = [
        JellyfinTrack(id="live", name="Kings of the Carnival Creation (Live in Oslo)"),
    ]

    matches, unmatched_local = match_tracks(provider_tracks, local_tracks)

    assert len(matches) == 1
    assert matches[0].jellyfin_item_id == "live"
    assert matches[0].match_type == "normalized"
    assert not unmatched_local


def test_reports_local_tracks_not_present_in_provider_list() -> None:
    provider_tracks = [ProviderTrack(title="Army of the Night", rank=1)]
    local_tracks = [
        JellyfinTrack(id="1", name="Army of the Night"),
        JellyfinTrack(id="2", name="Sanctified with Dynamite"),
    ]

    matches, unmatched_local = match_tracks(provider_tracks, local_tracks)

    assert len(matches) == 1
    assert unmatched_local == ["Sanctified with Dynamite"]
