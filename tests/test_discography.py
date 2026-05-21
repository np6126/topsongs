import os
import time

from topsongs.discography import DiscographyCache, _within_one_edit, compute_artist_gap
from topsongs.models import Discography, DiscographyAlbum, JellyfinTrack


def _track(name: str) -> JellyfinTrack:
    return JellyfinTrack(id=name, name=name)


def test_compute_artist_gap_counts_owned_and_missing() -> None:
    local = [_track("Battery"), _track("Master of Puppets"), _track("Welcome Home (Sanitarium)")]
    disco = Discography(
        artist_name="Metallica",
        albums=[
            DiscographyAlbum(
                title="Master of Puppets",
                tracks=[
                    "Battery",
                    "Master of Puppets",
                    "The Thing That Should Not Be",
                    "Welcome Home (Sanitarium)",
                    "Disposable Heroes",
                ],
            )
        ],
    )

    gap = compute_artist_gap("Metallica", local, disco)

    assert len(gap.albums) == 1
    album = gap.albums[0]
    assert album.total_tracks == 5
    assert album.owned_count == 3
    assert album.missing_titles == ["The Thing That Should Not Be", "Disposable Heroes"]
    assert not album.is_complete


def test_compute_artist_gap_matches_via_normalization() -> None:
    local = [_track("Enter Sandman - Remastered"), _track("Sad but True")]
    disco = Discography(
        artist_name="Metallica",
        albums=[
            DiscographyAlbum(
                title="Metallica",
                tracks=["Enter Sandman", "Sad But True", "Holier Than Thou"],
            )
        ],
    )

    gap = compute_artist_gap("Metallica", local, disco)

    album = gap.albums[0]
    assert album.owned_count == 2
    assert album.missing_titles == ["Holier Than Thou"]


def test_compute_artist_gap_dedups_albums_and_tracks() -> None:
    disco = Discography(
        artist_name="Metallica",
        albums=[
            DiscographyAlbum(
                title="Ride the Lightning",
                tracks=["Fight Fire with Fire", "Fight Fire With Fire", "Ride the Lightning"],
            ),
            DiscographyAlbum(title="Ride the Lightning", tracks=["Fight Fire with Fire"]),
        ],
    )

    gap = compute_artist_gap("Metallica", [], disco)

    assert len(gap.albums) == 1
    assert gap.albums[0].total_tracks == 2


def test_compute_artist_gap_skips_albums_without_tracks() -> None:
    disco = Discography(artist_name="A", albums=[DiscographyAlbum(title="Empty", tracks=[])])

    gap = compute_artist_gap("A", [], disco)

    assert gap.albums == []


def test_artist_gap_aggregate_properties() -> None:
    disco = Discography(
        artist_name="A",
        albums=[
            DiscographyAlbum(title="One", tracks=["a", "b"]),
            DiscographyAlbum(title="Two", tracks=["c", "d"]),
        ],
    )

    gap = compute_artist_gap("A", [_track("a"), _track("b"), _track("c")], disco)

    assert gap.total_tracks == 4
    assert gap.owned_tracks == 3
    assert gap.complete_album_count == 1


def test_within_one_edit() -> None:
    assert _within_one_edit("behelit", "behelit")
    assert _within_one_edit("enter the behelit", "enter the behelith")
    assert _within_one_edit("cat", "bat")
    assert _within_one_edit("cat", "ct")
    assert not _within_one_edit("cat", "dog")
    assert not _within_one_edit("abc", "abcde")


def test_compute_artist_gap_tolerates_single_typo() -> None:
    """A misspelled Last.fm track is still counted as owned (Behelit vs Behelith)."""
    local = [_track("Enter the Behelit")]
    disco = Discography(
        artist_name="Beast in Black",
        albums=[DiscographyAlbum(title="Enter The Behelith", tracks=["Enter The Behelith"])],
    )

    gap = compute_artist_gap("Beast in Black", local, disco)

    assert gap.albums[0].owned_count == 1
    assert gap.albums[0].missing_titles == []


def test_compute_artist_gap_collapses_typo_duplicate_album() -> None:
    local = [_track("Enter the Behelit")]
    disco = Discography(
        artist_name="Beast in Black",
        albums=[
            DiscographyAlbum(title="Enter The Behelit", tracks=["Enter The Behelit"]),
            DiscographyAlbum(title="Enter The Behelith", tracks=["Enter The Behelith"]),
        ],
    )

    gap = compute_artist_gap("Beast in Black", local, disco)

    assert len(gap.albums) == 1
    assert gap.albums[0].is_complete


def test_compute_artist_gap_keeps_singles() -> None:
    local = [_track("A Hit Single")]
    disco = Discography(
        artist_name="A",
        albums=[DiscographyAlbum(title="A Hit Single", tracks=["A Hit Single"])],
    )

    gap = compute_artist_gap("A", local, disco)

    assert len(gap.albums) == 1
    assert gap.albums[0].total_tracks == 1
    assert gap.albums[0].is_complete


def test_compute_artist_gap_does_not_fuzzy_match_short_titles() -> None:
    local = [_track("Hero")]
    disco = Discography(
        artist_name="A",
        albums=[DiscographyAlbum(title="X", tracks=["Hero", "Zero", "Nero"])],
    )

    gap = compute_artist_gap("A", local, disco)

    assert gap.albums[0].owned_count == 1
    assert gap.albums[0].missing_titles == ["Zero", "Nero"]


def test_compute_artist_gap_does_not_fuzzy_match_numbered_titles() -> None:
    local = [_track("Symphony Chapter 1")]
    disco = Discography(
        artist_name="A",
        albums=[
            DiscographyAlbum(
                title="X", tracks=["Symphony Chapter 1", "Symphony Chapter 2", "Other Song"]
            )
        ],
    )

    gap = compute_artist_gap("A", local, disco)

    assert gap.albums[0].owned_count == 1
    assert "Symphony Chapter 2" in gap.albums[0].missing_titles


def test_discography_cache_roundtrip(tmp_path) -> None:
    cache = DiscographyCache(tmp_path / "c", ttl_seconds=3600)
    disco = Discography(
        artist_name="Metallica",
        albums=[DiscographyAlbum(title="Reload", tracks=["Fuel"])],
    )

    assert cache.get("Metallica", "studio") is None
    cache.put("Metallica", "studio", disco)

    loaded = cache.get("Metallica", "studio")
    assert loaded is not None
    assert loaded.albums[0].title == "Reload"


def test_discography_cache_respects_ttl(tmp_path) -> None:
    cache = DiscographyCache(tmp_path / "c", ttl_seconds=3600)
    cache.put("A", "studio", Discography(artist_name="A", albums=[]))

    stale = time.time() - 7200
    os.utime(cache._path("A", "studio"), (stale, stale))

    assert cache.get("A", "studio") is None


def test_discography_cache_separates_scopes(tmp_path) -> None:
    cache = DiscographyCache(tmp_path / "c", ttl_seconds=3600)
    cache.put(
        "A", "studio", Discography(artist_name="A", albums=[DiscographyAlbum(title="Studio")])
    )
    cache.put("A", "all", Discography(artist_name="A", albums=[DiscographyAlbum(title="All")]))

    assert cache.get("A", "studio").albums[0].title == "Studio"
    assert cache.get("A", "all").albums[0].title == "All"
