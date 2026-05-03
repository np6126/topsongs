from __future__ import annotations

from collections.abc import Iterable

from .models import JellyfinTrack, ProviderTrack, TrackMatch
from .normalize import normalize_name


def match_tracks(
    provider_tracks: Iterable[ProviderTrack],
    local_tracks: Iterable[JellyfinTrack],
) -> tuple[list[TrackMatch], list[str]]:
    local_by_exact: dict[str, JellyfinTrack] = {}
    local_by_normalized: dict[str, JellyfinTrack] = {}
    local_track_list = list(local_tracks)

    for track in local_track_list:
        local_by_exact.setdefault(track.name, track)
        local_by_normalized.setdefault(normalize_name(track.name), track)

    matches: list[TrackMatch] = []
    used_local_ids: set[str] = set()

    for provider_track in provider_tracks:
        local = local_by_exact.get(provider_track.title)
        match_type = "exact"

        if local is None:
            local = local_by_normalized.get(normalize_name(provider_track.title))
            match_type = "normalized"

        if local is None or local.id in used_local_ids:
            continue

        used_local_ids.add(local.id)
        matches.append(
            TrackMatch(
                provider_title=provider_track.title,
                jellyfin_item_id=local.id,
                jellyfin_title=local.name,
                match_type=match_type,
                album=local.album,
            )
        )

    unmatched_local = [
        track.name for track in local_track_list if track.id not in used_local_ids
    ]

    return matches, unmatched_local
