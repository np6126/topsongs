"""Which playlists belong to topsongs: the nightly ones and the live ones.

A Jellyfin tag marks both, never the name. Live playlists carry LIVE_TAG; they
are made on request and nothing deletes them. The nightly run owns the
playlists with PLAYLIST_MANAGED_TAG, but never a live playlist.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Settings
    from .models import JellyfinPlaylist

LIVE_TAG = "topsongs-live"

# Before tags, the nightly playlists were recognized by this name prefix, the
# old default of PLAYLIST_NAME_PREFIX; the planner takes such playlists over.
LEGACY_PREFIX = "Top Songs - "


def is_live(playlist: JellyfinPlaylist) -> bool:
    return LIVE_TAG in playlist.tags


def is_nightly(playlist: JellyfinPlaylist, settings: Settings) -> bool:
    return settings.playlist_managed_tag in playlist.tags and not is_live(playlist)
