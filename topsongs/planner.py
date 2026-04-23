from __future__ import annotations

import logging
from datetime import datetime, timezone

from .config import Settings
from .filters import LibraryPathFilter, NameFilter, UserFilter
from .jellyfin import JellyfinClient
from .matcher import match_tracks
from .models import (
    ArtistPlan,
    JellyfinPlaylist,
    JellyfinUser,
    PlannedPlaylistTrack,
    PlaylistPlan,
    ProviderTrack,
    RunReport,
    TrackMatch,
    UserPlan,
)
from .normalize import normalize_name
from .providers.base import TopSongsProvider
from .providers.lastfm import LastFmError, LastFmNoTopTracksError, LastFmRateLimitError
from .sanitize import sanitize_untrusted_text

logger = logging.getLogger(__name__)


class Planner:
    def __init__(
        self,
        settings: Settings,
        jellyfin: JellyfinClient,
        provider: TopSongsProvider,
    ) -> None:
        self.settings = settings
        self.jellyfin = jellyfin
        self.provider = provider
        self._artist_filter = NameFilter(settings.artist_allowlist, settings.artist_denylist)
        self._user_filter = UserFilter(settings.user_allowlist, settings.user_denylist)
        self._library_path_filter = LibraryPathFilter(
            settings.library_path_allowlist,
            settings.library_path_denylist,
        )
        self._provider_track_cache: dict[str, list[ProviderTrack] | Exception] = {}

    def run(self) -> RunReport:
        started_at = datetime.now(timezone.utc)
        users = self.jellyfin.get_users()
        targeted_users = [user for user in users if self._user_filter.matches(user)]
        user_plans: list[UserPlan] = []
        total_artist_count = 0
        total_eligible_count = 0
        total_created_count = 0
        total_replaced_count = 0
        total_failed_user_count = 0
        total_failed_artist_count = 0

        for user in targeted_users:
            logger.info(
                "event=user_start user=%s user_id=%s",
                sanitize_untrusted_text(user.name),
                user.id,
            )
            try:
                user_plan = self._plan_for_user(user)
            except Exception as exc:
                total_failed_user_count += 1
                logger.exception(
                    "event=user_failed user=%s user_id=%s error=%s",
                    sanitize_untrusted_text(user.name),
                    user.id,
                    exc,
                )
                user_plan = self._failed_user_plan(user, exc)
            user_plans.append(user_plan)
            total_artist_count += user_plan.artist_count_seen
            total_eligible_count += user_plan.eligible_artist_count
            total_failed_artist_count += user_plan.failed_artist_count
            created_count, replaced_count = self._count_playlist_actions(user_plan)
            total_created_count += created_count
            total_replaced_count += replaced_count

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

    @staticmethod
    def _failed_user_plan(user: JellyfinUser, exc: Exception) -> UserPlan:
        return UserPlan(
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

    @staticmethod
    def _count_playlist_actions(user_plan: UserPlan) -> tuple[int, int]:
        created_count = 0
        replaced_count = 0
        for artist_plan in user_plan.artists:
            playlist_plan = artist_plan.playlist_plan
            if playlist_plan is None:
                continue
            if playlist_plan.action == "created":
                created_count += 1
            if playlist_plan.action == "replaced":
                replaced_count += 1
        return created_count, replaced_count

    def _plan_for_user(self, user: JellyfinUser) -> UserPlan:
        artists = self.jellyfin.get_artists(user.id)
        existing_playlists = {
            playlist.name: playlist
            for playlist in self.jellyfin.get_playlists_for_user(user.id)
        }
        eligible_count = 0
        planned_count = 0
        failed_artist_count = 0
        artist_plans: list[ArtistPlan] = []

        for artist in artists:
            if not self._artist_filter.matches(artist.name):
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
                plan = self._failed_artist_plan(artist.name, exc)

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
        local_tracks = self._library_path_filter.filter_tracks(all_local_tracks)
        filtered_out_count = len(all_local_tracks) - len(local_tracks)
        local_count = len(local_tracks)
        eligible = local_count > self.settings.min_tracks_per_artist
        plan = self._initial_artist_plan(artist.name, local_count, eligible)

        if filtered_out_count:
            plan.notes.append(
                f"Excluded {filtered_out_count} local tracks because they do not match "
                "the configured library path filters."
            )
            logger.info(
                "event=library_filtered user=%s artist=%s skipped_tracks=%s",
                sanitize_untrusted_text(user.name),
                sanitize_untrusted_text(artist.name),
                filtered_out_count,
            )

        if not eligible:
            plan.notes.append(
                f"Skipped because local track count {local_count} is not greater than "
                f"threshold {self.settings.min_tracks_per_artist}."
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
                f"provider=lastfm rate_limited user={sanitize_untrusted_text(user.name)} "
                f"artist={sanitize_untrusted_text(artist.name)} error={exc}"
            ) from exc
        except LastFmError as exc:
            raise RuntimeError(
                f"provider=lastfm request_failed user={sanitize_untrusted_text(user.name)} "
                f"artist={sanitize_untrusted_text(artist.name)} error={exc}"
            ) from exc

        plan.provider_tracks = provider_tracks

        matches, unmatched = match_tracks(provider_tracks, local_tracks)
        plan.matched_tracks = matches
        plan.unmatched_tracks = unmatched

        if matches:
            plan.playlist_plan = self._apply_playlist_plan(
                user=user,
                artist_name=artist.name,
                matches=matches,
                existing_playlists=existing_playlists,
                notes=plan.notes,
            )
        else:
            plan.notes.append(
                "No playlist planned because no provider tracks could be matched locally."
            )

        logger.info(
            "event=artist_done user=%s artist=%s local=%s provider_tracks=%s "
            "matched=%s unmatched=%s applied=%s",
            sanitize_untrusted_text(user.name),
            sanitize_untrusted_text(artist.name),
            local_count,
            len(provider_tracks),
            len(matches),
            len(unmatched),
            bool(plan.playlist_plan),
        )
        return plan

    def _initial_artist_plan(
        self,
        artist_name: str,
        local_track_count: int,
        eligible: bool,
    ) -> ArtistPlan:
        return ArtistPlan(
            artist=artist_name,
            local_track_count=local_track_count,
            eligible=eligible,
            provider=self.provider.name,
        )

    def _failed_artist_plan(self, artist_name: str, exc: Exception) -> ArtistPlan:
        return ArtistPlan(
            artist=artist_name,
            local_track_count=0,
            eligible=False,
            provider=self.provider.name,
            notes=["Artist processing failed."],
            error=str(exc),
        )

    @staticmethod
    def _playlist_name(artist_name: str) -> str:
        return f"Top Songs - {artist_name}"

    @staticmethod
    def _build_planned_tracks(matches: list[TrackMatch]) -> list[PlannedPlaylistTrack]:
        return [
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

    def _apply_playlist_plan(
        self,
        user: JellyfinUser,
        artist_name: str,
        matches: list[TrackMatch],
        existing_playlists: dict[str, JellyfinPlaylist],
        notes: list[str],
    ) -> PlaylistPlan:
        playlist_name = self._playlist_name(artist_name)
        item_ids = [match.jellyfin_item_id for match in matches]
        planned_tracks = self._build_planned_tracks(matches)
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
                notes.append(
                    f"Created replacement playlist {created_playlist_id}, but failed "
                    f"to delete previous playlist {existing_playlist.id}: {exc}"
                )
                logger.exception(
                    "event=playlist_delete_failed user=%s playlist=%s old_id=%s error=%s",
                    sanitize_untrusted_text(user.name),
                    sanitize_untrusted_text(playlist_name),
                    existing_playlist.id,
                    exc,
                )

        playlist_plan = PlaylistPlan(
            user_id=user.id,
            user_name=user.name,
            playlist_name=playlist_name,
            action=action,
            planned_item_ids=item_ids,
            planned_tracks=planned_tracks,
            deleted_playlist_id=deleted_playlist_id,
            created_playlist_id=created_playlist_id,
        )
        existing_playlists[playlist_name] = JellyfinPlaylist(
            id=created_playlist_id,
            name=playlist_name,
        )
        self._log_applied_playlist(
            user.name,
            playlist_name,
            action,
            created_playlist_id,
            planned_tracks,
        )
        return playlist_plan

    def _get_provider_tracks(self, artist_name: str) -> list[ProviderTrack]:
        cache_key = self._provider_cache_key(artist_name)
        cached = self._provider_track_cache.get(cache_key)
        if isinstance(cached, Exception):
            raise cached
        if cached is not None:
            logger.debug(
                "event=provider_cache_hit provider=lastfm artist=%s",
                sanitize_untrusted_text(artist_name),
            )
            return cached

        try:
            provider_tracks = self.provider.get_top_tracks(artist_name)
        except Exception as exc:
            self._provider_track_cache[cache_key] = exc
            raise

        self._provider_track_cache[cache_key] = provider_tracks
        return provider_tracks

    @staticmethod
    def _provider_cache_key(artist_name: str) -> str:
        return normalize_name(artist_name)

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
