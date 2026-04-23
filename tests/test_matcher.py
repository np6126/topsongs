from topsongs.matcher import match_tracks
from topsongs.models import JellyfinTrack, ProviderTrack


def test_match_exact_and_normalized() -> None:
    provider_tracks = [
        ProviderTrack(title="Army of the Night", rank=1),
        ProviderTrack(title="We Drink Your Blood - Remastered 2018", rank=2),
    ]
    local_tracks = [
        JellyfinTrack(id="1", name="Army of the Night", album="Blessed & Possessed"),
        JellyfinTrack(id="2", name="We Drink Your Blood", album="Preachers of the Night"),
    ]

    matches, unmatched = match_tracks(provider_tracks, local_tracks)

    assert len(matches) == 2
    assert not unmatched
    assert matches[0].match_type == "exact"
    assert matches[1].match_type == "normalized"
