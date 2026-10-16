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
        # Case-insensitive exact match. Providers and local tags routinely
        # differ only in title casing ("Kings Of The Carnival Creation" vs
        # "Kings of the Carnival Creation"); without folding, that miss falls
        # through to the normalized tier, where a live/remaster sibling can
        # steal the studio track's rank.
        local_by_exact.setdefault(track.name.casefold(), track)
        # Several recordings can collapse to one normalized key (a studio take
        # plus its live/remaster/demo editions). Keep the one closest to its
        # base form — the shortest title, i.e. the least alt-version cruft — so
        # the provider's studio rank resolves to the studio take, not an edition.
        normalized = normalize_name(track.name)
        incumbent = local_by_normalized.get(normalized)
        if incumbent is None or len(track.name) < len(incumbent.name):
            local_by_normalized[normalized] = track

    matches: list[TrackMatch] = []
    used_local_ids: set[str] = set()

    for provider_track in provider_tracks:
        local = local_by_exact.get(provider_track.title.casefold())
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
                year=local.year,
                play_count=local.play_count,
                is_favorite=local.is_favorite,
            )
        )

    unmatched_local = [
        track.name for track in local_track_list if track.id not in used_local_ids
    ]

    return matches, unmatched_local
