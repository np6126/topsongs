import pytest
from fakes import JellyfinStub, SetlistStub, concert, user, wire_cli

from topsongs import live, live_cli
from topsongs.models import ConcertFilter, JellyfinArtist, JellyfinTrack, SetlistArtist

_REAL_SETLISTFM_CLIENT = live.setlistfm_client

CONCERTS = [
    concert("future", [], day=30),
    concert("c3", ["Hit", "Deep Cut", "Closer"], day=12),
    concert("c2", ["Hit", "Closer"], day=10),
    concert("c1", ["Opener", "Hit"], day=5),
]


BAND = JellyfinArtist(id="a", name="Band", mbid="mb")
ALICE = user("alice")


def _wire(
    monkeypatch, tmp_path, *, artists=(BAND,), choice=(), isatty=True, users=(ALICE,)
) -> list:
    jellyfin = JellyfinStub(
        users=users,
        artists=artists,
        tracks=[
            JellyfinTrack(id="t-hit", name="Hit"),
            JellyfinTrack(id="t-closer", name="Closer"),
            JellyfinTrack(id="t-opener", name="Opener"),
        ],
    )
    stub = SetlistStub(CONCERTS, choice)
    wire_cli(monkeypatch, live_cli, tmp_path, jellyfin)
    monkeypatch.setattr(live, "setlistfm_client", lambda s: stub)
    monkeypatch.setattr(live_cli.sys.stdin, "isatty", lambda: isatty)
    return jellyfin.created


def test_list_shows_concerts_and_creates_nothing(monkeypatch, tmp_path, capsys):
    created = _wire(monkeypatch, tmp_path)

    assert live_cli.main(["Band", "--list"]) == 0

    out = capsys.readouterr().out
    assert "noch keine" in out and "12.10.2026" in out
    assert created == []


def test_default_is_newest_concert_with_setlist_in_running_order(monkeypatch, tmp_path):
    created = _wire(monkeypatch, tmp_path)

    assert live_cli.main(["Band", "--yes"]) == 0

    assert created == [("alice", "Live - Band - Arena, Köln (2026-10-12)", ["t-hit", "t-closer"])]


def test_last_n_mix_orders_by_play_count(monkeypatch, tmp_path):
    created = _wire(monkeypatch, tmp_path)

    assert live_cli.main(["Band", "--last", "3", "--min-share", "0", "--yes"]) == 0

    _, name, item_ids = created[0]
    assert name == "Live - Band - Tour - Mix aus 3 Konzerten (2026-10-05 – 2026-10-12)"
    assert item_ids == ["t-hit", "t-closer", "t-opener"]


def test_pick_and_dry_run(monkeypatch, tmp_path, capsys):
    created = _wire(monkeypatch, tmp_path)

    assert live_cli.main(["Band", "--pick", "3,4", "--dry-run"]) == 0

    assert created == []
    out = capsys.readouterr().out
    assert "Dry-Run" in out and "2/2" in out


def test_pick_of_upcoming_concert_fails(monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path)

    assert live_cli.main(["Band", "--pick", "1", "--yes"]) == 1
    assert "keine Setlist" in capsys.readouterr().out


def test_setlist_link_takes_artist_from_setlist(monkeypatch, tmp_path):
    created = _wire(monkeypatch, tmp_path)
    url = "https://www.setlist.fm/setlist/band/2026/arena-cologne-germany-c2.html"
    monkeypatch.setattr(live_cli, "parse_setlist_ref", lambda value: "c2")

    assert live_cli.main(["--setlist", url, "--yes"]) == 0

    assert created[0][2] == ["t-hit", "t-closer"]


def test_without_terminal_requires_yes(monkeypatch, tmp_path, capsys):
    created = _wire(monkeypatch, tmp_path, isatty=False)

    assert live_cli.main(["Band"]) == 1

    assert created == []
    assert "--yes" in capsys.readouterr().out


def test_ambiguous_artist_lists_candidates(monkeypatch, tmp_path, capsys):
    _wire(
        monkeypatch,
        tmp_path,
        artists=[JellyfinArtist(id="a", name="Band")],
        choice=[SetlistArtist(mbid="m1", name="Band"), SetlistArtist(mbid="m2", name="Band")],
    )

    assert live_cli.main(["Band", "--yes"]) == 1

    out = capsys.readouterr().out
    assert "--mbid" in out and "m1" in out and "m2" in out


def test_missing_key_is_reported(monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path)
    monkeypatch.setattr(live, "setlistfm_client", _REAL_SETLISTFM_CLIENT)
    monkeypatch.setattr(live_cli.Settings, "setlistfm_api_key", None)

    assert live_cli.main(["Band", "--yes"]) == 1
    assert "SETLISTFM_API_KEY" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["Band", "--last", "0"],
        ["Band", "--last", "21"],
        ["Band", "--min-share", "101"],
        ["Band", "--public", "--all-users"],
        ["Band", "--public", "--user", "alice,guest"],
    ],
)
def test_invalid_arguments_exit(argv):
    with pytest.raises(SystemExit):
        live_cli.main(argv)


def test_bracketed_text_from_setlistfm_is_printed_literally(monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path)
    CONCERTS[1].songs[1].cover_artist = "[traditional]"
    try:
        assert live_cli.main(["Band", "--dry-run"]) == 0
    finally:
        CONCERTS[1].songs[1].cover_artist = None

    assert "Cover von [traditional]" in capsys.readouterr().out


def test_custom_name_gets_the_live_prefix_in_preview_and_playlist(monkeypatch, tmp_path, capsys):
    created = _wire(monkeypatch, tmp_path)

    assert live_cli.main(["Band", "--name", "Mein Abend", "--yes"]) == 0

    assert "Live - Mein Abend" in capsys.readouterr().out
    assert created[0][1] == "Live - Mein Abend"


def test_place_filters_go_to_setlistfm_search(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)

    assert live_cli.main(["Band", "--list", "--city", "Köln", "--country", "de"]) == 0

    assert live.setlistfm_client(None).searched == [ConcertFilter(city="Köln", country="de")]


TEAM = (ALICE, user("guest"), user("gone", disabled=True))


@pytest.mark.parametrize(
    "argv",
    [["--user", "guest,alice"], ["--user", "guest", "--user", "alice", "--user", "guest"]],
)
def test_several_users_each_get_a_private_copy(monkeypatch, tmp_path, argv):
    created = _wire(monkeypatch, tmp_path, users=TEAM)

    assert live_cli.main(["Band", "--yes", *argv]) == 0

    assert [entry[0] for entry in created] == ["guest", "alice"]
    assert live_cli.JellyfinClient.public == [False, False]


def test_all_users_skips_disabled_ones(monkeypatch, tmp_path, capsys):
    created = _wire(monkeypatch, tmp_path, users=TEAM)

    assert live_cli.main(["Band", "--yes", "--all-users"]) == 0

    assert [entry[0] for entry in created] == ["alice", "guest"]
    assert "Für: alice, guest" in capsys.readouterr().out


def test_public_creates_one_playlist_for_everyone(monkeypatch, tmp_path, capsys):
    created = _wire(monkeypatch, tmp_path, users=TEAM)

    assert live_cli.main(["Band", "--yes", "--public", "--user", "guest"]) == 0

    assert [entry[0] for entry in created] == ["guest"]
    assert live_cli.JellyfinClient.public == [True]
    assert "Öffentlich" in capsys.readouterr().out


def test_unknown_user_in_the_list_creates_nothing(monkeypatch, tmp_path, capsys):
    created = _wire(monkeypatch, tmp_path, users=TEAM)

    assert live_cli.main(["Band", "--yes", "--user", "alice,ghost"]) == 1

    assert created == []
    assert "'ghost' nicht gefunden" in capsys.readouterr().out
