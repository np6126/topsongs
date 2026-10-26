from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlencode

import httpx

from .http import REQUEST_ERRORS, send_with_retries
from .models import (
    JellyfinArtist,
    JellyfinPlaylist,
    JellyfinTrack,
    JellyfinUser,
    JellyfinUserPolicy,
    PlaybackEvent,
)

logger = logging.getLogger(__name__)


class JellyfinClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        # One pooled client per run: httpx.Client is thread-safe and reuses
        # keep-alive connections across requests instead of dialing each time.
        self._client = httpx.Client(
            timeout=self.timeout_seconds,
            headers=self.default_headers,
        )

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            # Jellyfin 12 rejects the legacy X-Emby-Token header (401).
            "Authorization": f'MediaBrowser Token="{self.api_key}"',
            "Accept": "application/json",
        }

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "JellyfinClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def get_users(self) -> list[JellyfinUser]:
        payload = self._get("/Users", params={})
        return [
            self._user_from_item(item)
            for item in payload
            if item.get("Id") and item.get("Name")
        ]

    def get_artists(self, user_id: str) -> list[JellyfinArtist]:
        params = {
            "UserId": user_id,
            "Recursive": "true",
            "SortBy": "SortName",
            "Fields": "SortName,ProviderIds",
        }
        items = self._get_all_items("/Artists/AlbumArtists", params=params)
        return [
            JellyfinArtist(
                id=item["Id"],
                name=item.get("Name", ""),
                sort_name=item.get("SortName"),
                mbid=(item.get("ProviderIds") or {}).get("MusicBrainzArtist") or None,
            )
            for item in items
            if item.get("Id") and item.get("Name")
        ]

    def get_tracks_for_artist(self, user_id: str, artist: JellyfinArtist) -> list[JellyfinTrack]:
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Audio",
            "ArtistIds": artist.id,
            "SortBy": "Album,SortName",
            "Fields": (
                "Path,ProviderIds,Album,Artists,RunTimeTicks,"
                "ParentIndexNumber,IndexNumber,UserData"
            ),
        }
        items = self._get_all_items(f"/Users/{user_id}/Items", params=params)
        return [
            self._track_from_item(item)
            for item in items
            if item.get("Id") and item.get("Name")
        ]

    def get_audio_playback_events(self) -> list[PlaybackEvent]:
        """Audio playback starts and stops from the activity log (needs an admin API key)."""
        # The log holds tens of thousands of entries, so page in bigger steps.
        entries = self._get_all_items(
            "/System/ActivityLog/Entries", params={"hasUserId": "true"}, page_size=5000
        )
        return [
            PlaybackEvent(
                user_id=entry["UserId"],
                item_id=entry["ItemId"],
                started=entry["Type"] == "AudioPlayback",
                at=datetime.fromisoformat(entry["Date"]),
            )
            for entry in entries
            if entry.get("Type") in ("AudioPlayback", "AudioPlaybackStopped")
            and entry.get("ItemId")
        ]

    def get_playlists_for_user(
        self, user_id: str, media_types: str | None = "Audio"
    ) -> list[JellyfinPlaylist]:
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Playlist",
            "SortBy": "SortName",
            # Tags identify the playlists topsongs owns; the list
            # endpoint omits them unless explicitly requested.
            "Fields": "Tags",
        }
        # media_types=None returns playlists of every media type; the default
        # keeps the audio-only behaviour the planner relies on.
        if media_types is not None:
            params["MediaTypes"] = media_types
        items = self._get_all_items(f"/Users/{user_id}/Items", params=params)
        return [
            JellyfinPlaylist(
                id=item["Id"],
                name=item.get("Name", ""),
                tags=item.get("Tags") or [],
            )
            for item in items
            if item.get("Id") and item.get("Name")
        ]

    def create_playlist(
        self, user_id: str, playlist_name: str, item_ids: list[str], public: bool = False
    ) -> str:
        # A public playlist is visible to every user, not only its owner.
        body = {
            "Name": playlist_name,
            "Ids": item_ids,
            "UserId": user_id,
            "MediaType": "Audio",
            "IsPublic": public,
        }
        payload = self._post_json("/Playlists", body)
        playlist_id = payload.get("Id")
        if not playlist_id:
            raise RuntimeError(f"Playlist creation for '{playlist_name}' did not return an Id.")
        return str(playlist_id)

    def delete_playlist(self, playlist_id: str) -> None:
        self._delete(f"/Items/{playlist_id}")

    def rename_playlist(self, user_id: str, playlist_id: str, new_name: str) -> None:
        # Jellyfin (10.11) has no working name-only playlist update: both
        # POST /Playlists/{id} and GET /Items/{id} return 400. The web client's
        # path works: read the full item DTO through the user-scoped endpoint,
        # change only Name, and post it back via UpdateItem (POST /Items/{id},
        # which returns 204). Track membership and visibility are not DTO fields,
        # so a name-only round-trip leaves them untouched.
        dto = self._get(f"/Users/{user_id}/Items/{playlist_id}", params={})
        dto["Name"] = new_name
        self._post_json(f"/Items/{playlist_id}", dto)

    def add_managed_tag(self, user_id: str, playlist_id: str, tag: str) -> None:
        # Same UpdateItem round-trip as rename_playlist: read the full item DTO
        # through the user-scoped endpoint, append the tag, and post it back via
        # POST /Items/{id}. Idempotent — a playlist that already carries the tag
        # needs no write.
        dto = self._get(f"/Users/{user_id}/Items/{playlist_id}", params={})
        tags = dto.get("Tags") or []
        if tag in tags:
            return
        tags.append(tag)
        dto["Tags"] = tags
        self._post_json(f"/Items/{playlist_id}", dto)

    def set_overview(self, user_id: str, playlist_id: str, overview: str) -> None:
        # Same UpdateItem round-trip as rename_playlist; Overview is the
        # description Jellyfin shows on the playlist page.
        dto = self._get(f"/Users/{user_id}/Items/{playlist_id}", params={})
        dto["Overview"] = overview
        self._post_json(f"/Items/{playlist_id}", dto)

    def _get_all_items(
        self, path: str, params: dict[str, str], page_size: int = 500
    ) -> list[dict]:
        start_index = 0
        all_items: list[dict] = []
        while True:
            payload = self._get(
                path,
                {**params, "Limit": str(page_size), "StartIndex": str(start_index)},
            )
            page = payload.get("Items", [])
            all_items.extend(page)
            if len(all_items) >= payload.get("TotalRecordCount", len(all_items)) or not page:
                break
            start_index += len(page)
        return all_items

    def _get(self, path: str, params: dict[str, str]) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("GET %s?%s", url, urlencode(params))
        return self._request_json("GET", url, params=params)

    def _post_json(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("POST %s (json body)", url)
        return self._request_json("POST", url, params=None, json_body=body)

    def _delete(self, path: str) -> None:
        url = f"{self.base_url}{path}"
        logger.debug("DELETE %s", url)
        self._request_no_content("DELETE", url)

    def _request_json(
        self, method: str, url: str, params: dict[str, str] | None, json_body: dict | None = None
    ) -> dict:
        response = self._request(method, url, params=params, json_body=json_body)
        if not response.content:
            return {}
        return response.json()

    def _request_no_content(self, method: str, url: str) -> None:
        self._request(method, url, params=None)

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None,
        json_body: dict | None = None,
    ) -> httpx.Response:
        def send() -> httpx.Response:
            response = self._client.request(method, url, params=params, json=json_body)
            response.raise_for_status()
            return response

        try:
            return send_with_retries(
                send,
                max_retries=self.max_retries,
                backoff_seconds=self.retry_backoff_seconds,
                log_context=f"service=jellyfin method={method} url={url}",
            )
        except REQUEST_ERRORS as exc:
            raise RuntimeError(
                f"service=jellyfin method={method} url={url} message=request_failed error={exc}"
            ) from exc

    @staticmethod
    def _user_from_item(item: dict) -> JellyfinUser:
        policy = item.get("Policy") or {}
        return JellyfinUser(
            id=item["Id"],
            name=item.get("Name", ""),
            policy=JellyfinUserPolicy(
                is_administrator=bool(policy.get("IsAdministrator", False)),
                is_disabled=bool(policy.get("IsDisabled", False)),
                is_hidden=bool(policy.get("IsHidden", False)),
                enable_all_folders=bool(policy.get("EnableAllFolders", False)),
                enabled_folders=policy.get("EnabledFolders") or [],
            ),
        )

    @staticmethod
    def _track_from_item(item: dict) -> JellyfinTrack:
        user_data = item.get("UserData") or {}
        return JellyfinTrack(
            id=item["Id"],
            name=item.get("Name", ""),
            artists=item.get("Artists") or [],
            album=item.get("Album"),
            path=item.get("Path"),
            runtime_ticks=item.get("RunTimeTicks"),
            index_number=item.get("IndexNumber"),
            parent_index_number=item.get("ParentIndexNumber"),
            provider_ids=item.get("ProviderIds") or {},
            year=item.get("ProductionYear"),
            play_count=int(user_data.get("PlayCount") or 0),
            is_favorite=bool(user_data.get("IsFavorite", False)),
        )

