"""Test doubles shared by the test modules; pytest puts tests/ on sys.path."""
from __future__ import annotations

from datetime import date

from topsongs.models import Concert, ConcertFilter, ConcertSong, JellyfinUser, JellyfinUserPolicy


def user(name: str, disabled: bool = False) -> JellyfinUser:
    return JellyfinUser(id=name, name=name, policy=JellyfinUserPolicy(is_disabled=disabled))


class ClientCM:
    """Client basics: takes any constructor arguments and works in `with` blocks."""

    def __init__(self, **kwargs) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class SettingsStub:
    """The settings the CLIs and the web services read, with test values."""

    jellyfin_url = "http://jellyfin:8096"
    jellyfin_api_key = "jellyfin-key"
    lastfm_api_key = "lastfm-key"
    setlistfm_api_key = "setlistfm-key"
    request_timeout_seconds = 20
    request_max_retries = 2
    retry_backoff_seconds = 1.0
    min_request_interval = 0.0
    max_provider_tracks = 75
    log_level = "INFO"
    dry_run = False
    playlist_name_prefix = "Top Songs - "
    playlist_managed_tag = "topsongs"
    live_playlist_prefix = "Live - "
    user_allowlist: list[str] = []
    user_denylist: list[str] = []
    artist_allowlist: list[str] = []
    artist_denylist: list[str] = []
    library_path_allowlist: list[str] = []
    library_path_denylist: list[str] = []


def settings(**overrides) -> SettingsStub:
    return type("Settings", (SettingsStub,), overrides)()


def wire_cli(monkeypatch, cli_module, tmp_path, jellyfin, **overrides) -> None:
    """Point a CLI module at stub settings (state in tmp_path) and a stub Jellyfin client."""
    settings_cls = type("Settings", (SettingsStub,), {"state_dir": tmp_path, **overrides})
    monkeypatch.setattr(cli_module, "Settings", settings_cls)
    monkeypatch.setattr(cli_module, "JellyfinClient", jellyfin)
    monkeypatch.setattr(cli_module, "configure_logging", lambda level: None)


class JellyfinStub(ClientCM):
    """Jellyfin client over fixed data; records its writes.

    tracks are keyed by artist id and playlists by user id; a plain list applies
    to every artist or user. Calling the stub returns it, so it can also stand in
    for the JellyfinClient class.
    """

    def __init__(
        self,
        *,
        users=(),
        artists=(),
        tracks=(),
        playlists=(),
        overview_error=None,
        tag_error=None,
        delete_error=None,
    ):
        self.users = list(users)
        self.artists = list(artists)
        self.tracks = tracks
        self.playlists = playlists
        self.overview_error = overview_error
        self.tag_error = tag_error
        self.delete_error = delete_error
        self.created: list[tuple] = []
        self.public: list[bool] = []  # create_playlist's public flag, per created playlist
        self.overviews: list[tuple] = []
        self.tagged: list[tuple] = []
        self.deleted: list[str] = []
        self.renamed: list[tuple] = []

    def __call__(self, **kwargs) -> JellyfinStub:
        return self

    def get_users(self):
        return self.users

    def get_artists(self, user_id):
        return self.artists

    def get_tracks_for_artist(self, user_id, artist):
        return _for_key(self.tracks, artist.id)

    def get_playlists_for_user(self, user_id, media_types="Audio"):
        return _for_key(self.playlists, user_id)

    def create_playlist(self, user_id, name, item_ids, public=False):
        self.created.append((user_id, name, item_ids))
        self.public.append(public)
        return "new-id"

    def add_managed_tag(self, user_id, playlist_id, tag):
        if self.tag_error:
            raise self.tag_error
        self.tagged.append((playlist_id, tag))

    def set_overview(self, user_id, playlist_id, overview):
        if self.overview_error:
            raise self.overview_error
        self.overviews.append((playlist_id, overview))

    def delete_playlist(self, playlist_id):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append(playlist_id)

    def rename_playlist(self, user_id, playlist_id, new_name):
        self.renamed.append((playlist_id, new_name))


def _for_key(items, key) -> list:
    return list(items.get(key, [])) if isinstance(items, dict) else list(items)


def concert(
    cid: str,
    songs: list[str],
    *,
    day: int = 1,
    venue: str = "Arena",
    city: str = "Köln",
    tour: str | None = "Tour",
    encore_from: int | None = None,
) -> Concert:
    """A setlist.fm concert in October 2026; songs from encore_from on are encores."""
    return Concert(
        id=cid,
        url=f"https://www.setlist.fm/setlist/x/2026/{cid}.html",
        event_date=date(2026, 10, day),
        artist_name="Band",
        venue_id=f"v-{venue}",
        venue_name=venue,
        city=city,
        tour=tour,
        songs=[
            ConcertSong(title=title, encore=encore_from is not None and index >= encore_from)
            for index, title in enumerate(songs)
        ],
    )


class SetlistStub(ClientCM):
    """setlist.fm client over a fixed list of concerts; records the searches."""

    def __init__(self, concerts: list[Concert], candidates=()) -> None:
        self.concerts = concerts
        self.candidates = list(candidates)
        self.searched: list[ConcertFilter] = []

    def artist_setlists(self, mbid):
        return self.concerts

    def search_setlists(self, mbid, concert_filter):
        self.searched.append(concert_filter)
        return [c for c in self.concerts if c.tour == concert_filter.tour]

    def setlist(self, setlist_id):
        return next(c for c in self.concerts if c.id == setlist_id)

    def search_artists(self, name):
        return self.candidates
