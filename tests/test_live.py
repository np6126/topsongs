from types import SimpleNamespace

import pytest
from fakes import JellyfinStub, concert, settings, user

from topsongs import live
from topsongs.models import (
    JellyfinArtist,
    JellyfinPlaylist,
    JellyfinTrack,
    LiveMix,
    MixSong,
    SetlistArtist,
)

USER = user("alice")


# --------------------------------------------------------------------------- #
# build_mix
# --------------------------------------------------------------------------- #

def test_single_concert_keeps_running_order():
    songs, below = live.build_mix([concert("a", ["Intro", "Hit", "Ballad", "Closer"])], 0.5)

    assert [s.title for s in songs] == ["Intro", "Hit", "Ballad", "Closer"]
    assert below == []


def test_mix_puts_most_played_first_then_show_position():
    concerts = [
        concert("a", ["Opener", "Rare", "Hit", "Closer"]),
        concert("b", ["Opener", "Hit", "Closer"]),
        concert("c", ["Opener", "Hit", "Other", "Closer"]),
    ]

    songs, below = live.build_mix(concerts, 0.0)

    # Played at all three first, by median show position; then the one-offs,
    # Rare (a third into its show) before Other (two thirds in).
    assert [(s.title, s.play_count) for s in songs] == [
        ("Opener", 3),
        ("Hit", 3),
        ("Closer", 3),
        ("Rare", 1),
        ("Other", 1),
    ]
    assert below == []


def test_threshold_moves_rare_songs_below():
    concerts = [
        concert("a", ["Core", "Sometimes", "Rare"]),
        concert("b", ["Core", "Sometimes"]),
        concert("c", ["Core"]),
    ]

    songs, below = live.build_mix(concerts, 0.66)

    assert [s.title for s in songs] == ["Core", "Sometimes"]
    assert [s.title for s in below] == ["Rare"]


def test_full_threshold_can_leave_no_song():
    songs, below = live.build_mix([concert("a", ["X"]), concert("b", ["Y"])], 1.0)

    assert songs == []
    assert [s.title for s in below] == ["X", "Y"]


def test_reprise_counts_once_per_concert_and_most_common_spelling_wins():
    concerts = [
        concert("a", ["Song", "Middle", "Song (Reprise)"]),
        concert("b", ["song"]),
        concert("c", ["Song"]),
    ]

    songs, _ = live.build_mix(concerts, 0.0)

    first = songs[0]
    assert (first.title, first.play_count) == ("Song", 3)


def test_encore_flag_follows_majority():
    concerts = [
        concert("a", ["A", "B"], encore_from=1),
        concert("b", ["A", "B"], encore_from=1),
        concert("c", ["A", "B"]),
    ]

    songs, _ = live.build_mix(concerts, 0.0)

    assert {s.title: s.encore for s in songs} == {"A": False, "B": True}


# --------------------------------------------------------------------------- #
# Concert selection
# --------------------------------------------------------------------------- #

def test_select_skips_concerts_without_setlist_and_takes_last_n():
    concerts = [
        concert("upcoming", [], day=20),
        concert("c", ["x"], day=12),
        concert("b", ["x"], day=10),
        concert("a", ["x"], day=5),
    ]

    picked = live.select_concerts(concerts, last=2)

    assert [c.id for c in picked] == ["c", "b"]


def test_select_per_venue_keeps_newest_night_per_venue():
    concerts = [
        concert("berlin2", ["x"], day=12, venue="Olympiastadion"),
        concert("berlin1", ["x"], day=11, venue="Olympiastadion"),
        concert("wien", ["x"], day=5, venue="Happel"),
        concert("prag", ["x"], day=1, venue="Letnany"),
    ]

    picked = live.select_concerts(concerts, last=2, per_venue=True)

    assert [c.id for c in picked] == ["berlin2", "wien"]


def test_pick_concerts_by_number_and_errors():
    concerts = [concert("upcoming", [], day=20), concert("a", ["x"]), concert("b", ["y"])]

    assert [c.id for c in live.pick_concerts(concerts, [3, 2, 3])] == ["b", "a"]
    with pytest.raises(live.LiveError, match="keine Setlist"):
        live.pick_concerts(concerts, [1])
    with pytest.raises(live.LiveError, match="gibt es nicht"):
        live.pick_concerts(concerts, [4])


def test_load_concerts_uses_search_only_with_filters():
    calls = []
    client = SimpleNamespace(
        artist_setlists=lambda mbid: calls.append(("list", mbid)) or [concert("a", ["x"], day=1)],
        search_setlists=lambda mbid, f: calls.append(("search", mbid, f.tour, f.city))
        or [concert("old", ["x"], day=1), concert("new", ["x"], day=9)],
    )

    live.load_concerts(client, "m")
    live.load_concerts(client, "m", live.ConcertFilter(tour="  "))
    newest_first = live.load_concerts(client, "m", live.ConcertFilter(tour="T", city="Berlin"))

    assert calls == [
        ("list", "m"),
        ("list", "m"),
        ("search", "m", "T", "Berlin"),
    ]
    assert [c.id for c in newest_first] == ["new", "old"]


def test_suggestions_are_distinct_and_sorted():
    concerts = [
        concert("a", ["x"], day=1, venue="Arena", city="Köln", tour="B"),
        concert("b", ["x"], day=2, venue="arena hall", city="Köln", tour="a"),
        concert("c", [], day=3, venue="Arena", city="Bonn", tour=None),
    ]
    concerts[0].country_code = "DE"

    assert live.suggestions(concerts) == {
        "tour": ["a", "B"],
        "year": ["2026"],
        "venue": ["Arena", "arena hall"],
        "city": ["Bonn", "Köln"],
        "country": ["DE"],
    }


# --------------------------------------------------------------------------- #
# Artist resolution
# --------------------------------------------------------------------------- #

def test_find_library_artist_groups_spelling_variants():
    jellyfin = JellyfinStub(
        artists=[
            JellyfinArtist(id="1", name="Blackmore's Night"),
            JellyfinArtist(id="2", name="Blackmore’s Night", mbid="mb"),
            JellyfinArtist(id="3", name="Rainbow"),
        ]
    )

    artist = live.find_library_artist(jellyfin, USER, "Blackmore's Night")

    assert [a.id for a in artist.artists] == ["1", "2"]
    assert artist.mbid == "mb"


def test_find_library_artist_unknown_raises():
    with pytest.raises(live.LiveError, match="nicht in der Bibliothek"):
        live.find_library_artist(JellyfinStub(), USER, "Nobody")


def _library_artist(mbid=None, name="Ghost"):
    return live.LibraryArtist(name=name, artists=[JellyfinArtist(id="1", name=name, mbid=mbid)])


def test_resolve_mbid_prefers_override_then_tags():
    client = SimpleNamespace(search_artists=lambda name: pytest.fail("no search expected"))

    assert live.resolve_mbid(client, _library_artist("tag"), "given") == "given"
    assert live.resolve_mbid(client, _library_artist("tag")) == "tag"


def test_resolve_mbid_uses_unique_exact_search_hit():
    client = SimpleNamespace(
        search_artists=lambda name: [
            SetlistArtist(mbid="m1", name="Ghost"),
            SetlistArtist(mbid="m2", name="Ghost Bath"),
        ]
    )

    assert live.resolve_mbid(client, _library_artist()) == "m1"


def test_resolve_mbid_ambiguous_asks_for_choice():
    candidates = [SetlistArtist(mbid="m1", name="Ghost"), SetlistArtist(mbid="m2", name="Ghost")]
    client = SimpleNamespace(search_artists=lambda name: candidates)

    with pytest.raises(live.ArtistChoiceNeeded) as exc:
        live.resolve_mbid(client, _library_artist())

    assert [c.mbid for c in exc.value.candidates] == ["m1", "m2"]


def test_resolve_mbid_without_hits_raises():
    client = SimpleNamespace(search_artists=lambda name: [])

    with pytest.raises(live.LiveError, match="kennt keinen"):
        live.resolve_mbid(client, _library_artist())


# --------------------------------------------------------------------------- #
# Library matching
# --------------------------------------------------------------------------- #

def test_local_tracks_for_merges_variants_and_applies_path_filter():
    tracks = {
        "1": [JellyfinTrack(id="t1", name="Hit", path="/music/a/hit.flac")],
        "2": [
            JellyfinTrack(id="t1", name="Hit", path="/music/a/hit.flac"),
            JellyfinTrack(id="t2", name="Closer (Remastered 2020)", path="/music/a/c.flac"),
            JellyfinTrack(id="t3", name="Rare", path="/music/podcasts/rare.mp3"),
        ],
    }
    jellyfin = JellyfinStub(tracks=tracks)
    artist = live.LibraryArtist(
        name="Band",
        artists=[JellyfinArtist(id="1", name="Band"), JellyfinArtist(id="2", name="Band")],
    )

    no_podcasts = settings(library_path_denylist=["/music/podcasts"])
    tracks = live.local_tracks_for(no_podcasts, jellyfin, USER, artist)

    assert sorted(t.id for t in tracks) == ["t1", "t2"]


def test_build_live_mix_matches_library_and_splits_by_threshold():
    tracks = [
        JellyfinTrack(id="t1", name="Hit"),
        JellyfinTrack(id="t2", name="Closer (Remastered 2020)"),
    ]
    concerts = [concert("a", ["Hit", "Rare", "Closer"]), concert("b", ["Hit", "Closer"])]

    mix = live.build_live_mix("Band", concerts, tracks, 1.0)

    assert [(s.title, s.jellyfin_item_id) for s in mix.songs] == [("Hit", "t1"), ("Closer", "t2")]
    assert [(s.title, s.jellyfin_item_id) for s in mix.below_threshold] == [("Rare", None)]
    assert [s.title for s in mix.matched] == ["Hit", "Closer"]


def test_build_live_mix_counts_a_concert_given_twice_once():
    mix = live.build_live_mix("Band", [concert("a", ["X"]), concert("a", ["X"])], [], 1.0)

    assert len(mix.concerts) == 1 and mix.songs[0].play_count == 1


@pytest.mark.parametrize(
    "concerts,message",
    [([], "Keine Konzerte"), ([concert("future", [])], "Noch keine Setlist: Arena, Köln")],
)
def test_build_live_mix_rejects_empty_selection_and_concerts_without_setlist(concerts, message):
    with pytest.raises(live.LiveError, match=message):
        live.build_live_mix("Band", concerts, [], 0.5)


def test_split_live_by_tag_not_name():
    playlists = [
        JellyfinPlaylist(id="1", name="Konzert", tags=["topsongs-live"]),
        JellyfinPlaylist(id="2", name="Live - selbst gemacht"),
    ]

    found, others = live.split_live(playlists)

    assert [p.id for p in found] == ["1"] and [p.id for p in others] == ["2"]


# --------------------------------------------------------------------------- #
# Naming and creation
# --------------------------------------------------------------------------- #

def test_suggest_name_single_concert():
    name = live.suggest_name("Live - ", "Metallica", [concert("a", ["x"], day=12)])

    assert name == "Live - Metallica - Arena, Köln (2026-10-12)"


def test_suggest_name_mix_of_one_tour_and_of_mixed_tours():
    one_tour = [concert("a", ["x"], day=12), concert("b", ["x"], day=5)]
    mixed = [concert("a", ["x"], day=12), concert("b", ["x"], day=5, tour=None)]

    assert (
        live.suggest_name("Live - ", "Band", one_tour)
        == "Live - Band - Tour - Mix aus 2 Konzerten (2026-10-05 – 2026-10-12)"
    )
    assert (
        live.suggest_name("Live - ", "Band", mixed)
        == "Live - Band - Mix aus 2 Konzerten (2026-10-05 – 2026-10-12)"
    )


def test_suggest_name_replaces_path_unsafe_characters():
    name = live.suggest_name("Live - ", "AC/DC", [concert("a", ["x"], venue="Hall: West")])

    assert "/" not in name and ":" not in name


def test_unique_name_counts_up():
    assert live.unique_name("X", set()) == "X"
    assert live.unique_name("X", {"X", "X (2)"}) == "X (3)"


def _mix(*songs, concerts=None):
    return LiveMix(
        artist_name="Band",
        concerts=concerts or [concert("a", ["x"])],
        songs=list(songs),
        min_share=0.5,
    )


def test_create_live_playlist_adds_matched_songs_in_order_with_attribution():
    jellyfin = JellyfinStub(playlists=[JellyfinPlaylist(id="p", name="Live - Band")])
    mix = _mix(
        MixSong(title="A", play_count=1, jellyfin_item_id="t1"),
        MixSong(title="B", play_count=1),
        MixSong(title="C", play_count=1, jellyfin_item_id="t3"),
    )

    created = live.create_live_playlist(jellyfin, USER, mix, "Live - Band", "Live - ")

    assert jellyfin.created == [("alice", "Live - Band (2)", ["t1", "t3"])]
    assert jellyfin.tagged == [("new-id", "topsongs-live")]
    assert (created.name, created.track_count, created.warning) == ("Live - Band (2)", 2, None)
    assert "setlist.fm" in jellyfin.overviews[0][1]
    assert "https://www.setlist.fm/setlist/x/2026/a.html" in jellyfin.overviews[0][1]
    assert jellyfin.deleted == []


@pytest.mark.parametrize(
    "failure,expected",
    [
        ({"overview_error": RuntimeError("boom")}, "Beschreibung"),
        ({"tag_error": RuntimeError("boom")}, "Live-Tag"),
    ],
)
def test_create_live_playlist_keeps_playlist_when_a_later_step_fails(failure, expected):
    jellyfin = JellyfinStub(**failure)
    mix = _mix(MixSong(title="A", play_count=1, jellyfin_item_id="t1"))

    created = live.create_live_playlist(jellyfin, USER, mix, "Live - Band", "Live - ")

    assert created.playlist_id == "new-id"
    assert expected in created.warning
    assert jellyfin.deleted == []


def test_create_live_playlist_refuses_without_matches():
    jellyfin = JellyfinStub()

    with pytest.raises(live.LiveError):
        live.create_live_playlist(
            jellyfin, USER, _mix(MixSong(title="A", play_count=1)), "Live - Band", "Live - "
        )
    assert jellyfin.created == []


@pytest.mark.parametrize(
    "given,created",
    [
        ("Mein Konzert", "Live - Mein Konzert"),
        ("Live - Mein Konzert", "Live - Mein Konzert"),
        ("Live -Mein Konzert", "Live - Mein Konzert"),
        ("Live Aid 1985", "Live - Live Aid 1985"),
    ],
)
def test_create_live_playlist_always_carries_the_prefix(given, created):
    jellyfin = JellyfinStub()
    mix = _mix(MixSong(title="A", play_count=1, jellyfin_item_id="t1"))

    live.create_live_playlist(jellyfin, USER, mix, given, "Live - ")

    assert jellyfin.created[0][1] == created


def test_create_live_playlist_refuses_a_bare_prefix():
    mix = _mix(MixSong(title="A", play_count=1, jellyfin_item_id="t1"))

    with pytest.raises(live.LiveError, match="leer"):
        live.create_live_playlist(JellyfinStub(), USER, mix, "Live - ", "Live - ")


def test_overview_names_threshold_only_for_mixes():
    single = _mix()
    double = _mix(concerts=[concert("a", ["x"]), concert("b", ["x"])])

    assert "mindestens" not in live.overview_text(single)
    assert "mindestens 50 %" in live.overview_text(double)


def test_setlistfm_client_requires_key():
    with pytest.raises(live.LiveError, match="SETLISTFM_API_KEY"):
        live.setlistfm_client(SimpleNamespace(setlistfm_api_key=None))
