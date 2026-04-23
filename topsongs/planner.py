from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .jellyfin import JellyfinClient
from .matcher import match_tracks
from .models import (
    ArtistPlan,
    JellyfinPlaylist,
    JellyfinTrack,
    JellyfinUser,
    PlannedPlaylistTrack,
    PlaylistPlan,
    RunReport,
    UserPlan,
)
from .normalize import normalize_name
from .providers.lastfm import LastFmError, LastFmNoTopTracksError, LastFmRateLimitError
from .providers.base import TopSongsProvider
from .sanitize import sanitize_untrusted_text

logger = logging.getLogger(__name__)


class Planner:
    def __init__(self, settings: Settings, jellyfin: JellyfinClient, provider: TopSongsProvider) -> None:
        self.settings = settings
        self.jellyfin = jellyfin
        self.provider = provider
        self._library_path_allowlist = [self._normalize_path_prefix(item) for item in settings.library_path_allowlist]
        self._library_path_denylist = [self._normalize_path_prefix(item) for item in settings.library_path_denylist]
        self._provider_track_cache: dict[str, Any] = {}

    def run(self) -> RunReport:
        started_at = datetime.now(timezone.utc)
        users = self.jellyfin.get_users()
        targeted_users = [user for user in users if self._user_is_selected(user)]
        user_plans: list[UserPlan] = []
        total_artist_count = 0
        total_eligible_count = 0
        total_created_count = 0
        total_replaced_count = 0
        total_failed_user_count = 0
        total_failed_artist_count = 0

        for user in targeted_users:
            logger.info("event=user_start user=%s user_id=%s", sanitize_untrusted_text(user.name), user.id)
            try:
                user_plan = self._plan_for_user(user)
            except Exception as exc:
                total_failed_user_count += 1
                logger.exception("event=user_failed user=%s user_id=%s error=%s", sanitize_untrusted_text(user.name), user.id, exc)
                user_plan = UserPlan(
                    user_id=user.id,
                    user_name=user.name,
                    is_administrator=user.policy.is_administrator,
                    artist_count_seen=0,
                    eligible_artist_count=0,
                    planned_playlist_count=0,
                    failed_artist_count=0,
                    notes=["User processing failed before artist iteration completed."],
                    error=str(exc),
                )
            user_plans.append(user_plan)
            total_artist_count += user_plan.artist_count_seen
            total_eligible_count += user_plan.eligible_artist_count
            total_failed_artist_count += user_plan.failed_artist_count
            total_created_count += sum(
                1 for artist_plan in user_plan.artists if artist_plan.playlist_plan and artist_plan.playlist_plan.action == "created"
            )
            total_replaced_count += sum(
                1 for artist_plan in user_plan.artists if artist_plan.playlist_plan and artist_plan.playlist_plan.action == "replaced"
            )

        finished_at = datetime.now(timezone.utc)
        return RunReport(
            started_at=started_at,
            finished_at=finished_at,
            provider=self.provider.name,
            user_count_seen=len(users),
            targeted_user_count=len(targeted_users),
            artist_count_seen=total_artist_count,
            eligible_artist_count=total_eligible_count,
            created_playlist_count=total_created_count,
            replaced_playlist_count=total_replaced_count,
            failed_user_count=total_failed_user_count,
            failed_artist_count=total_failed_artist_count,
            users=user_plans,
        )

    def _artist_is_selected(self, artist_name: str) -> bool:
        normalized = normalize_name(artist_name)

        if self.settings.artist_allowlist:
            allowed = {normalize_name(item) for item in self.settings.artist_allowlist}
            if normalized not in allowed:
                return False

        if self.settings.artist_denylist:
            denied = {normalize_name(item) for item in self.settings.artist_denylist}
            if normalized in denied:
                return False

        return True

    def _user_is_selected(self, user: JellyfinUser) -> bool:
        normalized = normalize_name(user.name)

        if self.settings.user_allowlist:
            allowed = {normalize_name(item) for item in self.settings.user_allowlist}
            if normalized not in allowed:
                return False

        if self.settings.user_denylist:
            denied = {normalize_name(item) for item in self.settings.user_denylist}
            if normalized in denied:
                return False

        return not user.policy.is_disabled

    def _plan_for_user(self, user: JellyfinUser) -> UserPlan:
        artists = self.jellyfin.get_artists(user.id)
        existing_playlists = {playlist.name: playlist for playlist in self.jellyfin.get_playlists_for_user(user.id)}
        eligible_count = 0
        planned_count = 0
        failed_artist_count = 0
        artist_plans: list[ArtistPlan] = []

        for artist in artists:
            if not self._artist_is_selected(artist.name):
                continue
            try:
                plan = self._plan_for_artist(user, artist, existing_playlists)
            except Exception as exc:
                failed_artist_count += 1
                logger.exception(
                    "event=artist_failed user=%s artist=%s error=%s",
                    sanitize_untrusted_text(user.name),
                    sanitize_untrusted_text(artist.name),
                    exc,
                )
                plan = ArtistPlan(
                    artist=artist.name,
                    local_track_count=0,
                    eligible=False,
                    provider=self.provider.name,
                    notes=["Artist processing failed."],
                    error=str(exc),
                )

            if plan.eligible:
                eligible_count += 1
            if plan.playlist_plan:
                planned_count += 1
            artist_plans.append(plan)

        return UserPlan(
            user_id=user.id,
            user_name=user.name,
            is_administrator=user.policy.is_administrator,
            artist_count_seen=len(artists),
            eligible_artist_count=eligible_count,
            planned_playlist_count=planned_count,
            failed_artist_count=failed_artist_count,
            artists=artist_plans,
        )

    def _plan_for_artist(
        self,
        user: JellyfinUser,
        artist,
        existing_playlists: dict[str, JellyfinPlaylist],
    ) -> ArtistPlan:
        all_local_tracks = self.jellyfin.get_tracks_for_artist(user.id, artist)
        local_tracks = self._filter_tracks_by_library_path(all_local_tracks)
        filtered_out_count = len(all_local_tracks) - len(local_tracks)
        local_count = len(local_tracks)
        eligible = local_count > self.settings.min_tracks_per_artist
        plan = ArtistPlan(
            artist=artist.name,
            local_track_count=local_count,
            eligible=eligible,
            provider=self.provider.name,
        )

        if filtered_out_count:
            plan.notes.append(
                f"Excluded {filtered_out_count} local tracks because they do not match the configured library path filters."
            )
            logger.info(
                "event=library_filtered user=%s artist=%s skipped_tracks=%s",
                sanitize_untrusted_text(user.name),
                sanitize_untrusted_text(artist.name),
                filtered_out_count,
            )

        if not eligible:
            plan.notes.append(
                f"Skipped because local track count {local_count} is not greater than threshold {self.settings.min_tracks_per_artist}."
            )
            return plan

        try:
            provider_tracks = self._get_provider_tracks(artist.name)
        except LastFmNoTopTracksError as exc:
            plan.notes.append(f"No Last.fm top tracks returned: {exc}")
            logger.info(
                "event=provider_empty provider=lastfm user=%s artist=%s",
                sanitize_untrusted_text(user.name),
                sanitize_untrusted_text(artist.name),
            )
            return plan
        except LastFmRateLimitError as exc:
            raise RuntimeError(
                f"provider=lastfm rate_limited user={sanitize_untrusted_text(user.name)} artist={sanitize_untrusted_text(artist.name)} error={exc}"
            ) from exc
        except LastFmError as exc:
            raise RuntimeError(
                f"provider=lastfm request_failed user={sanitize_untrusted_text(user.name)} artist={sanitize_untrusted_text(artist.name)} error={exc}"
            ) from exc

        plan.provider_tracks = provider_tracks

        matches, unmatched = match_tracks(provider_tracks, local_tracks)
        plan.matched_tracks = matches
        plan.unmatched_tracks = unmatched

        if matches:
            playlist_name = f"Top Songs - {artist.name}"
            item_ids = [match.jellyfin_item_id for match in matches]
            planned_tracks = [
                PlannedPlaylistTrack(
                    rank=index,
                    provider_title=match.provider_title,
                    jellyfin_title=match.jellyfin_title,
                    jellyfin_item_id=match.jellyfin_item_id,
                    match_type=match.match_type,
                    album=match.album,
                )
                for index, match in enumerate(matches, start=1)
            ]
            existing_playlist = existing_playlists.get(playlist_name)
            created_playlist_id = self.jellyfin.create_playlist(user.id, playlist_name, item_ids)
            deleted_playlist_id = None
            action = "created"

            if existing_playlist is not None:
                action = "replaced"
                deleted_playlist_id = existing_playlist.id
                try:
                    self.jellyfin.delete_playlist(existing_playlist.id)
                    logger.info(
                        "event=playlist_deleted user=%s playlist=%s playlist_id=%s",
                        sanitize_untrusted_text(user.name),
                        sanitize_untrusted_text(playlist_name),
                        existing_playlist.id,
                    )
                except Exception as exc:
                    plan.notes.append(
                        f"Created replacement playlist {created_playlist_id}, but failed to delete previous playlist {existing_playlist.id}: {exc}"
                    )
                    logger.exception(
                        "event=playlist_delete_failed user=%s playlist=%s old_id=%s error=%s",
                        sanitize_untrusted_text(user.name),
                        sanitize_untrusted_text(playlist_name),
                        existing_playlist.id,
                        exc,
                    )

            plan.playlist_plan = PlaylistPlan(
                user_id=user.id,
                user_name=user.name,
                playlist_name=playlist_name,
                action=action,
                planned_item_ids=item_ids,
                planned_tracks=planned_tracks,
                deleted_playlist_id=deleted_playlist_id,
                created_playlist_id=created_playlist_id,
            )
            existing_playlists[playlist_name] = JellyfinPlaylist(id=created_playlist_id, name=playlist_name)
            self._log_applied_playlist(user.name, playlist_name, action, created_playlist_id, planned_tracks)
        else:
            plan.notes.append("No playlist planned because no provider tracks could be matched locally.")

        logger.info(
            "event=artist_done user=%s artist=%s local=%s provider_tracks=%s matched=%s unmatched=%s applied=%s",
            sanitize_untrusted_text(user.name),
            sanitize_untrusted_text(artist.name),
            local_count,
            len(provider_tracks),
            len(matches),
            len(unmatched),
            bool(plan.playlist_plan),
        )
        return plan

    def _get_provider_tracks(self, artist_name: str):
        cache_key = normalize_name(artist_name)
        cached = self._provider_track_cache.get(cache_key)
        if isinstance(cached, Exception):
            raise cached
        if cached is not None:
            logger.debug("event=provider_cache_hit provider=lastfm artist=%s", sanitize_untrusted_text(artist_name))
            return cached

        try:
            provider_tracks = self.provider.get_top_tracks(artist_name)
        except Exception as exc:
            self._provider_track_cache[cache_key] = exc
            raise

        self._provider_track_cache[cache_key] = provider_tracks
        return provider_tracks

    def _filter_tracks_by_library_path(self, tracks: Iterable[JellyfinTrack]) -> list[JellyfinTrack]:
        filtered: list[JellyfinTrack] = []
        for track in tracks:
            normalized_path = self._normalize_track_path(track.path)
            if not self._path_is_selected(normalized_path):
                continue
            filtered.append(track)
        return filtered

    def _path_is_selected(self, normalized_path: str | None) -> bool:
        if self._library_path_allowlist:
            if normalized_path is None:
                return False
            if not any(self._path_matches_prefix(normalized_path, prefix) for prefix in self._library_path_allowlist):
                return False

        if self._library_path_denylist:
            if normalized_path is not None and any(
                self._path_matches_prefix(normalized_path, prefix) for prefix in self._library_path_denylist
            ):
                return False

        return True

    @staticmethod
    def _normalize_track_path(path: str | None) -> str | None:
        if not path:
            return None
        return path.replace("\\", "/").rstrip("/").casefold()

    @staticmethod
    def _normalize_path_prefix(path: str) -> str:
        normalized = path.replace("\\", "/").rstrip("/").casefold()
        return normalized or "/"

    @staticmethod
    def _path_matches_prefix(path: str, prefix: str) -> bool:
        return path == prefix or path.startswith(f"{prefix}/")

    def _log_applied_playlist(
        self,
        user_name: str,
        playlist_name: str,
        action: str,
        playlist_id: str,
        planned_tracks: list[PlannedPlaylistTrack],
    ) -> None:
        logger.info(
            "event=playlist_applied user=%s playlist=%s action=%s playlist_id=%s track_count=%s",
            sanitize_untrusted_text(user_name),
            sanitize_untrusted_text(playlist_name),
            action,
            playlist_id,
            len(planned_tracks),
        )
        for track in planned_tracks:
            safe_jellyfin_title = sanitize_untrusted_text(track.jellyfin_title)
            safe_provider_title = sanitize_untrusted_text(track.provider_title)
            safe_album = sanitize_untrusted_text(track.album) if track.album else None
            description = f"  {track.rank}. {safe_jellyfin_title}"
            if safe_provider_title != safe_jellyfin_title:
                description += f" <- {safe_provider_title}"
            description += f" [{track.match_type}]"
            if safe_album:
                description += f" ({safe_album})"
            logger.info(description)
