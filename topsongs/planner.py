from __future__ import annotations

import logging
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from typing import NamedTuple

from .config import Settings
from .filters import LibraryPathFilter, NameFilter, UserFilter
from .jellyfin import JellyfinClient
from .matcher import match_tracks
from .models import (
    ArtistPlan,
    JellyfinArtist,
    JellyfinPlaylist,
    JellyfinTrack,
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
from .ranking import rerank_matches
from .sanitize import sanitize_for_filename, sanitize_untrusted_text

logger = logging.getLogger(__name__)


class _ArtistCounts(NamedTuple):
    eligible: int
    planned: int
    failed: int


class _PreparedArtist(NamedTuple):
    artist: JellyfinArtist
    plan: ArtistPlan
    # Local tracks left after the library-path and short-track filters.
    local_tracks: list[JellyfinTrack]


def _spelling_key(name: str) -> str:
    """Fold case and punctuation out of an artist name.

    Not normalize_name: that also drops diacritics, which would make
    "Motörhead" and "Motorhead" one name. A name made only of punctuation
    (e.g. "!!!") keeps its exact spelling.
    """
    folded = re.sub(r"[\W_]+", " ", unicodedata.normalize("NFC", name).casefold())
    return folded.strip() or name


class Planner:
    def __init__(
        self,
        settings: Settings,
        jellyfin: JellyfinClient,
        provider: TopSongsProvider,
    ) -> None:
        # jellyfin and provider are borrowed: the caller (cli.main) owns their
        # HTTP clients and closes them; the Planner must not close them itself.
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
        self._cache_lock = threading.Lock()

    def run(self) -> RunReport:
        started_at = datetime.now(timezone.utc)
        users = self.jellyfin.get_users()
        targeted_users = [user for user in users if self._user_filter.matches(user)]
        user_plans: list[UserPlan] = []
        total_artist_count = 0
        total_eligible_count = 0
        total_created_count = 0
        total_replaced_count = 0
        total_orphan_deleted_count = 0
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
            total_orphan_deleted_count += user_plan.orphan_deleted_count

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
            orphan_deleted_count=total_orphan_deleted_count,
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
            orphan_deleted_count=0,
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
        # Built once, then read-only while the pool runs: worker tasks only
        # .get() from it. _delete_orphan_playlists mutates it (del), which is
        # safe only because that step runs strictly after the pool has joined.
        existing_playlists = {
            playlist.name: playlist
            for playlist in self.jellyfin.get_playlists_for_user(user.id)
            if self._is_managed(playlist)
        }
        filtered = [artist for artist in artists if self._artist_filter.matches(artist.name)]
        runnable, collision_plans, protected_names = self._resolve_collisions(
            user, filtered, existing_playlists
        )

        with ThreadPoolExecutor(max_workers=self.settings.run_concurrency) as executor:
            fetched = list(
                executor.map(partial(self._fetch_tracks, user), [a for _, a in runnable])
            )
            to_finish, settled_plans = self._prepare_artists(user, runnable, fetched)
            finished = executor.map(
                partial(self._finish_artist_safe, user, existing_playlists=existing_playlists),
                to_finish.values(),
            )
            computed = dict(zip(to_finish, finished, strict=True))

        by_index = {**collision_plans, **settled_plans, **computed}
        # A lost result would silently drop an artist; fail loudly instead.
        assert len(by_index) == len(filtered)
        artist_plans = [by_index[index] for index in range(len(filtered))]

        counts, planned_playlist_names = self._aggregate_artist_plans(
            artist_plans, existing_playlists, protected_names
        )

        user_notes: list[str] = []
        orphan_deleted_count = self._delete_orphan_playlists(
            user=user,
            existing_playlists=existing_playlists,
            planned_playlist_names=planned_playlist_names,
            notes=user_notes,
        )

        return UserPlan(
            user_id=user.id,
            user_name=user.name,
            is_administrator=user.policy.is_administrator,
            artist_count_seen=len(artists),
            eligible_artist_count=counts.eligible,
            planned_playlist_count=counts.planned,
            orphan_deleted_count=orphan_deleted_count,
            failed_artist_count=counts.failed,
            artists=artist_plans,
            notes=user_notes,
        )

    def _resolve_collisions(
        self,
        user: JellyfinUser,
        filtered_artists: list[JellyfinArtist],
        existing_playlists: dict[str, JellyfinPlaylist],
    ) -> tuple[list[tuple[int, JellyfinArtist]], dict[int, ArtistPlan], set[str]]:
        """Claim playlist names up front, in artist order, before the pool runs.

        Two artists can sanitize to the same playlist name. Deciding the winner
        here — rather than dynamically as playlists are created — keeps the
        outcome deterministic under concurrency: the first artist in
        get_artists() order claims the name. The name is derived with the same
        _playlist_name() call _apply_playlist_plan uses, so no two pool tasks
        ever target the same playlist.
        """
        runnable: list[tuple[int, JellyfinArtist]] = []
        collision_plans: dict[int, ArtistPlan] = {}
        protected_names: set[str] = set()
        claimed_by: dict[str, str] = {}
        for index, artist in enumerate(filtered_artists):
            expected_name = self._playlist_name(artist.name)
            if expected_name in claimed_by:
                logger.warning(
                    "event=playlist_name_collision user=%s playlist=%s "
                    "first_artist=%s second_artist=%s",
                    sanitize_untrusted_text(user.name),
                    sanitize_untrusted_text(expected_name),
                    sanitize_untrusted_text(claimed_by[expected_name]),
                    sanitize_untrusted_text(artist.name),
                )
                plan = self._initial_artist_plan(artist.name, 0, False)
                plan.notes.append(
                    f"Playlist name collision: '{expected_name}' already claimed by "
                    f"'{claimed_by[expected_name]}' after name sanitization."
                )
                collision_plans[index] = plan
                # The collision winner may not produce a playlist, so an
                # existing playlist of this name is shielded from orphan
                # deletion here regardless.
                if expected_name in existing_playlists:
                    protected_names.add(expected_name)
                continue
            claimed_by[expected_name] = artist.name
            runnable.append((index, artist))
        return runnable, collision_plans, protected_names

    def _fetch_tracks(
        self, user: JellyfinUser, artist: JellyfinArtist
    ) -> list[JellyfinTrack] | Exception:
        """Fetch an artist's tracks in the pool, returning a failure as a value.

        executor.map would re-raise inside the orchestrator; returning the
        exception keeps one artist's failure from aborting the others.
        KeyboardInterrupt and SystemExit are BaseException and pass through.
        """
        try:
            return self.jellyfin.get_tracks_for_artist(user.id, artist)
        except Exception as exc:
            return exc

    def _prepare_artists(
        self,
        user: JellyfinUser,
        runnable: list[tuple[int, JellyfinArtist]],
        fetched: list[list[JellyfinTrack] | Exception],
    ) -> tuple[dict[int, _PreparedArtist], dict[int, ArtistPlan]]:
        """Sequential pass between the fetch and finish phases, in artist order.

        Drops duplicates: Jellyfin can hold one band as two artists (seen live:
        "Blackmore's Night" with ' and with U+2019). An eligible artist whose
        name equals an earlier one's up to case and punctuation AND whose
        local tracks are identical gets no playlist; its old one is left to
        orphan cleanup. Both are required so that look-alike names with other
        tracks, and artists sharing only a duet album, stay apart.

        Returns the artists still to finish and the plans already settled
        (failed, ineligible or duplicate), both keyed by artist index.
        """
        to_finish: dict[int, _PreparedArtist] = {}
        settled: dict[int, ArtistPlan] = {}
        # (spelling key, local track ids) -> first artist with that pair
        claimed_by: dict[tuple[str, frozenset[str]], str] = {}
        for (index, artist), tracks in zip(runnable, fetched, strict=True):
            if isinstance(tracks, Exception):
                settled[index] = self._failed_artist_plan(user, artist.name, tracks)
                continue
            prepared = self._prepare_artist(user, artist, tracks)
            if not prepared.plan.eligible:
                settled[index] = prepared.plan
                continue
            key = (
                _spelling_key(artist.name),
                frozenset(track.id for track in prepared.local_tracks),
            )
            if key in claimed_by:
                first_artist = claimed_by[key]
                logger.warning(
                    "event=artist_duplicate user=%s artist=%s first_artist=%s",
                    sanitize_untrusted_text(user.name),
                    sanitize_untrusted_text(artist.name),
                    sanitize_untrusted_text(first_artist),
                )
                prepared.plan.eligible = False
                prepared.plan.notes.append(
                    f"Duplicate of '{first_artist}' (same name up to case and punctuation, "
                    "same local tracks), which already gets the playlist."
                )
                settled[index] = prepared.plan
                continue
            claimed_by[key] = artist.name
            to_finish[index] = prepared
        return to_finish, settled

    def _finish_artist_safe(
        self,
        user: JellyfinUser,
        prepared: _PreparedArtist,
        existing_playlists: dict[str, JellyfinPlaylist],
    ) -> ArtistPlan:
        """Run _finish_artist so a pool task never raises (see _fetch_tracks)."""
        try:
            return self._finish_artist(user, prepared, existing_playlists)
        except Exception as exc:
            return self._failed_artist_plan(user, prepared.artist.name, exc)

    def _aggregate_artist_plans(
        self,
        artist_plans: list[ArtistPlan],
        existing_playlists: dict[str, JellyfinPlaylist],
        protected_names: set[str],
    ) -> tuple[_ArtistCounts, set[str]]:
        """Sequential post-pass over the ordered plans.

        Tallies the report counts and collects every playlist name that must
        survive orphan cleanup. Runs after the pool join, so its writes to
        existing_playlists are single-threaded.
        """
        eligible = 0
        planned = 0
        failed = 0
        planned_playlist_names: set[str] = set(protected_names)
        for plan in artist_plans:
            if plan.error is not None:
                failed += 1
                # Preserve a failed artist's existing playlist from orphan deletion.
                existing_name = self._playlist_name(plan.artist)
                if existing_name in existing_playlists:
                    planned_playlist_names.add(existing_name)
            if plan.eligible:
                eligible += 1
            if plan.playlist_plan is not None:
                planned += 1
                name = plan.playlist_plan.playlist_name
                existing_playlists[name] = JellyfinPlaylist(
                    id=plan.playlist_plan.created_playlist_id,
                    name=name,
                )
                planned_playlist_names.add(name)
        return _ArtistCounts(eligible, planned, failed), planned_playlist_names

    def _plan_for_artist(
        self,
        user: JellyfinUser,
        artist,
        existing_playlists: dict[str, JellyfinPlaylist],
    ) -> ArtistPlan:
        """Plan one artist on its own, without the cross-artist duplicate check."""
        all_local_tracks = self.jellyfin.get_tracks_for_artist(user.id, artist)
        prepared = self._prepare_artist(user, artist, all_local_tracks)
        if not prepared.plan.eligible:
            return prepared.plan
        return self._finish_artist(user, prepared, existing_playlists)

    def _prepare_artist(
        self,
        user: JellyfinUser,
        artist: JellyfinArtist,
        all_local_tracks: list[JellyfinTrack],
    ) -> _PreparedArtist:
        """Filter the local tracks and decide eligibility (no I/O)."""
        path_filtered_tracks = self._library_path_filter.filter_tracks(all_local_tracks)
        local_tracks = self._filter_short_tracks(path_filtered_tracks)
        short_track_count = len(path_filtered_tracks) - len(local_tracks)
        local_count = len(local_tracks)
        eligible = local_count > self.settings.min_tracks_per_artist
        plan = self._initial_artist_plan(artist.name, local_count, eligible)

        path_filtered_out_count = len(all_local_tracks) - len(path_filtered_tracks)
        if path_filtered_out_count:
            plan.notes.append(
                f"Excluded {path_filtered_out_count} local tracks because they do not match "
                "the configured library path filters."
            )
            logger.info(
                "event=library_filtered user=%s artist=%s skipped_tracks=%s",
                sanitize_untrusted_text(user.name),
                sanitize_untrusted_text(artist.name),
                path_filtered_out_count,
            )

        if short_track_count:
            plan.notes.append(
                f"Excluded {short_track_count} local tracks shorter than "
                f"{self.settings.min_track_duration_seconds} seconds."
            )
            logger.info(
                "event=short_tracks_filtered user=%s artist=%s skipped_tracks=%s "
                "min_duration_seconds=%s",
                sanitize_untrusted_text(user.name),
                sanitize_untrusted_text(artist.name),
                short_track_count,
                self.settings.min_track_duration_seconds,
            )

        if not eligible:
            plan.notes.append(
                f"Skipped because local track count {local_count} is not greater than "
                f"threshold {self.settings.min_tracks_per_artist}."
            )
        return _PreparedArtist(artist, plan, local_tracks)

    def _finish_artist(
        self,
        user: JellyfinUser,
        prepared: _PreparedArtist,
        existing_playlists: dict[str, JellyfinPlaylist],
    ) -> ArtistPlan:
        """Rank an eligible artist's tracks and apply its playlist."""
        artist, plan, local_tracks = prepared

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

        matches, _ = match_tracks(provider_tracks, local_tracks)
        matches = rerank_matches(
            matches,
            self.settings.personalization_weight,
            recency_bonus=self.settings.recency_bonus or 0.0,
        )
        plan.matched_tracks = matches

        appended, duplicate_titles = self._build_unmatched_local_matches(
            local_tracks, matches
        )
        plan.unmatched_local_tracks = [match.jellyfin_title for match in appended]
        plan.duplicate_local_tracks = duplicate_titles

        playlist_tracks = list(matches)
        if self.settings.append_unmatched_songs:
            playlist_tracks.extend(appended)
        if playlist_tracks:
            plan.playlist_plan = self._apply_playlist_plan(
                user=user,
                artist_name=artist.name,
                matches=playlist_tracks,
                existing_playlists=existing_playlists,
                notes=plan.notes,
            )
        else:
            plan.notes.append(
                "No playlist planned because no provider tracks could be matched locally."
            )

        logger.info(
            "event=artist_done user=%s artist=%s local=%s provider_tracks=%s "
            "matched=%s unmatched_local=%s duplicate_local=%s applied=%s",
            sanitize_untrusted_text(user.name),
            sanitize_untrusted_text(artist.name),
            plan.local_track_count,
            len(provider_tracks),
            len(matches),
            len(appended),
            len(duplicate_titles),
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

    def _failed_artist_plan(
        self, user: JellyfinUser, artist_name: str, exc: Exception
    ) -> ArtistPlan:
        logger.error(
            "event=artist_failed user=%s artist=%s error=%s",
            sanitize_untrusted_text(user.name),
            sanitize_untrusted_text(artist_name),
            exc,
            exc_info=exc,
        )
        return ArtistPlan(
            artist=artist_name,
            local_track_count=0,
            eligible=False,
            provider=self.provider.name,
            notes=["Artist processing failed."],
            error=str(exc),
        )

    def _playlist_name(self, artist_name: str) -> str:
        # Tag mode identifies managed playlists by their tag, so the name needs
        # no prefix and can be bare.
        prefix = "" if self.settings.playlist_tag_managed else self.settings.playlist_name_prefix
        return f"{prefix}{sanitize_for_filename(artist_name)}"

    def _is_managed(self, playlist: JellyfinPlaylist) -> bool:
        if self.settings.playlist_tag_managed:
            return self.settings.playlist_managed_tag in playlist.tags
        return playlist.name.startswith(self.settings.playlist_name_prefix)

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
                play_count=match.play_count,
            )
            for index, match in enumerate(matches, start=1)
        ]

    def _build_unmatched_local_matches(
        self,
        local_tracks: list[JellyfinTrack],
        matches: list[TrackMatch],
    ) -> tuple[list[TrackMatch], list[str]]:
        """Build the appended block of local tracks the provider did not rank.

        A local track is skipped only when an identically-titled copy is already
        included (matched or already appended) — a genuine duplicate. Distinct
        editions of the same song (live/remaster/demo, whose title differs) are
        kept as their own entries so owning a track never drops it from the
        playlist. Returns ``(appended, duplicates)`` — the appended TrackMatches
        and the titles dropped as an identically-titled copy of an included one.
        """
        matched_ids = {match.jellyfin_item_id for match in matches}
        unmatched = [track for track in local_tracks if track.id not in matched_ids]
        if self.settings.personalization_weight > 0.0:
            # Surface the user's own heavy rotation: order the appended block by
            # play count (favorites first on ties) instead of album order. The
            # dedup loop below runs after this sort, so the most-played copy of
            # a duplicated song is the one kept.
            unmatched.sort(
                key=lambda track: (track.play_count, track.is_favorite),
                reverse=True,
            )

        seen = {match.jellyfin_title.casefold() for match in matches}
        appended: list[TrackMatch] = []
        duplicates: list[str] = []
        for track in unmatched:
            title_key = track.name.casefold()
            if title_key in seen:
                duplicates.append(track.name)
                continue
            seen.add(title_key)
            appended.append(
                TrackMatch(
                    provider_title=track.name,
                    jellyfin_item_id=track.id,
                    jellyfin_title=track.name,
                    match_type="unmatched_local",
                    album=track.album,
                    year=track.year,
                    play_count=track.play_count,
                    is_favorite=track.is_favorite,
                )
            )
        return appended, duplicates

    def _filter_short_tracks(self, tracks: list[JellyfinTrack]) -> list[JellyfinTrack]:
        min_duration_ticks = self.settings.min_track_duration_seconds * 10_000_000
        if min_duration_ticks <= 0:
            return tracks
        return [
            track
            for track in tracks
            if track.runtime_ticks is None or track.runtime_ticks >= min_duration_ticks
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
        action: str = "replaced" if existing_playlist is not None else "created"
        deleted_playlist_id: str | None = existing_playlist.id if existing_playlist else None

        if self.settings.dry_run:
            logger.info(
                "event=dry_run_playlist user=%s playlist=%s action=%s tracks=%s",
                sanitize_untrusted_text(user.name),
                sanitize_untrusted_text(playlist_name),
                action,
                len(item_ids),
            )
            created_playlist_id = "dry-run"
        else:
            created_playlist_id = self.jellyfin.create_playlist(user.id, playlist_name, item_ids)
            if self.settings.playlist_tag_managed:
                try:
                    self.jellyfin.add_managed_tag(
                        user.id, created_playlist_id, self.settings.playlist_managed_tag
                    )
                except Exception:
                    # In tag mode the tag is the only thing that makes a playlist
                    # discoverable: an untagged playlist is invisible to every
                    # future run, which can neither replace nor orphan-delete it.
                    # Roll the just-created playlist back so a tag failure cannot
                    # leak a permanent untagged duplicate, then fail this artist.
                    self._rollback_untagged_playlist(
                        user, playlist_name, created_playlist_id
                    )
                    raise
            if existing_playlist is not None:
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
        # existing_playlists is a read-only snapshot while the pool runs; the
        # bookkeeping update for this new playlist happens in
        # _aggregate_artist_plans, after the pool join.
        self._log_applied_playlist(
            user.name,
            playlist_name,
            action,
            created_playlist_id,
            planned_tracks,
        )
        return playlist_plan

    def _rollback_untagged_playlist(
        self,
        user: JellyfinUser,
        playlist_name: str,
        created_playlist_id: str,
    ) -> None:
        try:
            self.jellyfin.delete_playlist(created_playlist_id)
            logger.warning(
                "event=playlist_tag_rolled_back user=%s playlist=%s playlist_id=%s",
                sanitize_untrusted_text(user.name),
                sanitize_untrusted_text(playlist_name),
                created_playlist_id,
            )
        except Exception as cleanup_exc:
            # The original tagging error is re-raised by the caller; surface the
            # leaked untagged playlist here so it can be cleaned up by hand.
            logger.exception(
                "event=playlist_tag_rollback_failed user=%s playlist=%s "
                "playlist_id=%s error=%s",
                sanitize_untrusted_text(user.name),
                sanitize_untrusted_text(playlist_name),
                created_playlist_id,
                cleanup_exc,
            )

    def _delete_orphan_playlists(
        self,
        user: JellyfinUser,
        existing_playlists: dict[str, JellyfinPlaylist],
        planned_playlist_names: set[str],
        notes: list[str],
    ) -> int:
        orphan_deleted_count = 0

        for playlist_name, playlist in list(existing_playlists.items()):
            if not self._is_managed(playlist):
                continue
            if playlist_name in planned_playlist_names:
                continue
            if self.settings.dry_run:
                logger.info(
                    "event=dry_run_orphan_skip user=%s playlist=%s playlist_id=%s",
                    sanitize_untrusted_text(user.name),
                    sanitize_untrusted_text(playlist_name),
                    playlist.id,
                )
                continue
            try:
                self.jellyfin.delete_playlist(playlist.id)
                orphan_deleted_count += 1
                del existing_playlists[playlist_name]
                logger.info(
                    "event=playlist_orphan_deleted user=%s playlist=%s playlist_id=%s",
                    sanitize_untrusted_text(user.name),
                    sanitize_untrusted_text(playlist_name),
                    playlist.id,
                )
            except Exception as exc:
                notes.append(
                    f"Failed to delete orphan playlist {playlist.id} ({playlist_name}): {exc}"
                )
                logger.exception(
                    "event=playlist_orphan_delete_failed user=%s playlist=%s "
                    "playlist_id=%s error=%s",
                    sanitize_untrusted_text(user.name),
                    sanitize_untrusted_text(playlist_name),
                    playlist.id,
                    exc,
                )

        return orphan_deleted_count

    def _get_provider_tracks(self, artist_name: str) -> list[ProviderTrack]:
        cache_key = self._provider_cache_key(artist_name)
        with self._cache_lock:
            cached = self._provider_track_cache.get(cache_key)
        if cached is not None:
            if isinstance(cached, Exception):
                raise cached
            logger.debug(
                "event=provider_cache_hit provider=lastfm artist=%s",
                sanitize_untrusted_text(artist_name),
            )
            return cached

        # The network call runs outside the lock so concurrent artists do not
        # serialize on it. setdefault lets the first writer win; in the rare
        # case of two artist names normalizing to one cache key, the second
        # caller makes a harmless duplicate call and adopts the stored value.
        try:
            result: list[ProviderTrack] | Exception = self.provider.get_top_tracks(artist_name)
        except Exception as exc:
            result = exc

        with self._cache_lock:
            stored = self._provider_track_cache.setdefault(cache_key, result)
        if isinstance(stored, Exception):
            raise stored
        return stored

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
        if not logger.isEnabledFor(logging.DEBUG):
            return
        for track in planned_tracks:
            safe_jellyfin_title = sanitize_untrusted_text(track.jellyfin_title)
            safe_provider_title = sanitize_untrusted_text(track.provider_title)
            safe_album = sanitize_untrusted_text(track.album) if track.album else None
            description = f"  {track.rank}. {safe_jellyfin_title}"
            if safe_provider_title != safe_jellyfin_title:
                description += f" <- {safe_provider_title}"
            description += f" [{track.match_type}]"
            if track.play_count:
                description += f" plays={track.play_count}"
            if safe_album:
                description += f" ({safe_album})"
            logger.debug(description)
