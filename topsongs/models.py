from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class JellyfinArtist(BaseModel):
    id: str
    name: str
    sort_name: str | None = None


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
    index_number: int | None = None
    parent_index_number: int | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)


class JellyfinPlaylist(BaseModel):
    id: str
    name: str


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
    match_type: Literal["exact", "normalized"]
    album: str | None = None


class PlannedPlaylistTrack(BaseModel):
    rank: int
    provider_title: str
    jellyfin_title: str
    jellyfin_item_id: str
    match_type: Literal["exact", "normalized"]
    album: str | None = None


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
    unmatched_tracks: list[str] = Field(default_factory=list)
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
    failed_artist_count: int = 0
    artists: list[ArtistPlan] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


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
    failed_user_count: int = 0
    failed_artist_count: int = 0
    users: list[UserPlan]

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
            failed_user_count=0,
            failed_artist_count=0,
            users=[],
        )
