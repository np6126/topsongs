from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class JellyfinArtist(BaseModel):
    id: str
    name: str
    sort_name: str | None = None
    # MusicBrainz artist id from the tags; setlist.fm looks artists up by it.
    mbid: str | None = None


class JellyfinUserPolicy(BaseModel):
    is_administrator: bool = False
    is_disabled: bool = False
    is_hidden: bool = False
    enable_all_folders: bool = False
    enabled_folders: list[str] = Field(default_factory=list)


class JellyfinUser(BaseModel):
    id: str
    name: str
    policy: JellyfinUserPolicy = Field(default_factory=JellyfinUserPolicy)


class JellyfinTrack(BaseModel):
    id: str
    name: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    path: str | None = None
    runtime_ticks: int | None = None
    index_number: int | None = None
    parent_index_number: int | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)
    year: int | None = None
    play_count: int = 0
    is_favorite: bool = False


class PlaybackEvent(BaseModel):
    """An audio playback start or stop from Jellyfin's activity log."""

    user_id: str
    item_id: str
    started: bool
    at: datetime


class JellyfinPlaylist(BaseModel):
    id: str
    name: str
    tags: list[str] = Field(default_factory=list)


class ProviderTrack(BaseModel):
    title: str
    rank: int
    listeners: int | None = None
    playcount: int | None = None
    mbid: str | None = None
    url: str | None = None


class TrackMatch(BaseModel):
    provider_title: str
    jellyfin_item_id: str
    jellyfin_title: str
    match_type: Literal["exact", "normalized", "unmatched_local"]
    album: str | None = None
    year: int | None = None
    play_count: int = 0
    is_favorite: bool = False


class PlannedPlaylistTrack(BaseModel):
    rank: int
    provider_title: str
    jellyfin_title: str
    jellyfin_item_id: str
    match_type: Literal["exact", "normalized", "unmatched_local"]
    album: str | None = None
    play_count: int = 0


class PlaylistPlan(BaseModel):
    user_id: str
    user_name: str
    playlist_name: str
    action: Literal["created", "replaced"]
    planned_item_ids: list[str]
    planned_tracks: list[PlannedPlaylistTrack] = Field(default_factory=list)
    deleted_playlist_id: str | None = None
    created_playlist_id: str | None = None


class ArtistPlan(BaseModel):
    artist: str
    local_track_count: int
    eligible: bool
    provider: str
    provider_tracks: list[ProviderTrack] = Field(default_factory=list)
    matched_tracks: list[TrackMatch] = Field(default_factory=list)
    # Local tracks with no provider match whose title is *not* already present
    # in the playlist: genuine gaps in Last.fm's top tracks, plus distinct
    # editions (live/remaster/demo) of an included song.
    unmatched_local_tracks: list[str] = Field(default_factory=list)
    # Local tracks dropped from the appended block because an identically-titled
    # copy is already in the playlist.
    duplicate_local_tracks: list[str] = Field(default_factory=list)
    playlist_plan: PlaylistPlan | None = None
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class UserPlan(BaseModel):
    user_id: str
    user_name: str
    is_administrator: bool
    artist_count_seen: int
    eligible_artist_count: int
    planned_playlist_count: int
    orphan_deleted_count: int = 0
    failed_artist_count: int = 0
    artists: list[ArtistPlan] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class DiscographyAlbum(BaseModel):
    title: str
    mbid: str | None = None
    year: int | None = None
    playcount: int | None = None
    tracks: list[str] = Field(default_factory=list)


class Discography(BaseModel):
    artist_name: str
    albums: list[DiscographyAlbum] = Field(default_factory=list)


class AlbumGap(BaseModel):
    title: str
    year: int | None = None
    total_tracks: int = 0
    owned_count: int = 0
    missing_titles: list[str] = Field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.total_tracks > 0 and self.owned_count >= self.total_tracks

    @property
    def coverage(self) -> float:
        if self.total_tracks == 0:
            return 1.0
        return self.owned_count / self.total_tracks


class ArtistGap(BaseModel):
    artist_name: str
    albums: list[AlbumGap] = Field(default_factory=list)
    error: str | None = None

    @property
    def total_tracks(self) -> int:
        return sum(album.total_tracks for album in self.albums)

    @property
    def owned_tracks(self) -> int:
        return sum(album.owned_count for album in self.albums)

    @property
    def complete_album_count(self) -> int:
        return sum(1 for album in self.albums if album.is_complete)


class ConcertSong(BaseModel):
    title: str
    encore: bool = False
    # Original artist when the band played someone else's song.
    cover_artist: str | None = None


class Concert(BaseModel):
    """One setlist.fm setlist; songs in play order, tape intros left out."""

    id: str
    url: str | None = None
    event_date: date | None = None
    artist_name: str
    venue_id: str | None = None
    venue_name: str = ""
    city: str | None = None
    country_code: str | None = None
    tour: str | None = None
    songs: list[ConcertSong] = Field(default_factory=list)

    @property
    def venue_key(self) -> str:
        return self.venue_id or f"{self.venue_name}|{self.city}"

    @property
    def place(self) -> str:
        return ", ".join(part for part in (self.venue_name, self.city) if part)


class ConcertFilter(BaseModel):
    """Narrows the concert list via setlist.fm's search; blank fields are unset."""

    tour: str | None = None
    year: int | None = None
    venue: str | None = None
    city: str | None = None
    country: str | None = None

    @field_validator("tour", "venue", "city", "country")
    @classmethod
    def blank_is_unset(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    def is_set(self) -> bool:
        return any(self.model_dump().values())


class SetlistArtist(BaseModel):
    mbid: str
    name: str
    disambiguation: str | None = None


class MixSong(BaseModel):
    title: str
    # Concerts of the selection the song was played at.
    play_count: int
    encore: bool = False
    cover_artist: str | None = None
    jellyfin_item_id: str | None = None


class LiveMix(BaseModel):
    artist_name: str
    concerts: list[Concert]
    # Played at least min_share of the concerts, most played first.
    songs: list[MixSong]
    # Played, but at fewer concerts than min_share asks for.
    below_threshold: list[MixSong] = Field(default_factory=list)
    min_share: float

    @property
    def matched(self) -> list[MixSong]:
        return [song for song in self.songs if song.jellyfin_item_id]


class RunReport(BaseModel):
    started_at: datetime
    finished_at: datetime
    provider: str
    user_count_seen: int
    targeted_user_count: int
    artist_count_seen: int
    eligible_artist_count: int
    created_playlist_count: int
    replaced_playlist_count: int
    orphan_deleted_count: int = 0
    failed_user_count: int = 0
    failed_artist_count: int = 0
    users: list[UserPlan]

    @property
    def unmatched_local_track_count(self) -> int:
        """Distinct local tracks that are a genuine gap in the provider's top tracks."""
        return len(
            {
                (artist.artist, track_title)
                for user in self.users
                for artist in user.artists
                for track_title in artist.unmatched_local_tracks
            }
        )

    @property
    def duplicate_local_track_count(self) -> int:
        """Distinct local tracks dropped as duplicates of an already-included song."""
        return len(
            {
                (artist.artist, track_title)
                for user in self.users
                for artist in user.artists
                for track_title in artist.duplicate_local_tracks
            }
        )

    @classmethod
    def empty(cls, provider: str) -> "RunReport":
        now = datetime.now(timezone.utc)
        return cls(
            started_at=now,
            finished_at=now,
            provider=provider,
            user_count_seen=0,
            targeted_user_count=0,
            artist_count_seen=0,
            eligible_artist_count=0,
            created_playlist_count=0,
            replaced_playlist_count=0,
            orphan_deleted_count=0,
            failed_user_count=0,
            failed_artist_count=0,
            users=[],
        )
