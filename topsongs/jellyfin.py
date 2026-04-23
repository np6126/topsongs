from __future__ import annotations

import logging
import time
from urllib.parse import urlencode

import httpx

from .models import JellyfinArtist, JellyfinPlaylist, JellyfinTrack, JellyfinUser, JellyfinUserPolicy

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

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "X-Emby-Token": self.api_key,
            "Accept": "application/json",
        }

    def get_users(self) -> list[JellyfinUser]:
        payload = self._get("/Users", params={})
        return [self._user_from_item(item) for item in payload if item.get("Id") and item.get("Name")]

    def get_artists(self, user_id: str) -> list[JellyfinArtist]:
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "MusicArtist",
            "SortBy": "SortName",
            "Fields": "SortName",
        }
        payload = self._get(f"/Users/{user_id}/Items", params=params)
        artists = payload.get("Items", [])
        return [
            JellyfinArtist(
                id=item["Id"],
                name=item.get("Name", ""),
                sort_name=item.get("SortName"),
            )
            for item in artists
            if item.get("Id") and item.get("Name")
        ]

    def get_tracks_for_artist(self, user_id: str, artist: JellyfinArtist) -> list[JellyfinTrack]:
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Audio",
            "ArtistIds": artist.id,
            "SortBy": "Album,SortName",
            "Fields": "Path,ProviderIds,Album,Artists,ParentIndexNumber,IndexNumber",
        }
        payload = self._get(f"/Users/{user_id}/Items", params=params)
        tracks = payload.get("Items", [])
        return [self._track_from_item(item) for item in tracks if item.get("Id") and item.get("Name")]

    def get_playlists_for_user(self, user_id: str) -> list[JellyfinPlaylist]:
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Playlist",
            "MediaTypes": "Audio",
            "SortBy": "SortName",
        }
        payload = self._get(f"/Users/{user_id}/Items", params=params)
        items = payload.get("Items", [])
        return [
            JellyfinPlaylist(id=item["Id"], name=item.get("Name", ""))
            for item in items
            if item.get("Id") and item.get("Name")
        ]

    def create_playlist(self, user_id: str, playlist_name: str, item_ids: list[str]) -> str:
        params = {
            "Name": playlist_name,
            "Ids": ",".join(item_ids),
            "UserId": user_id,
            "MediaType": "Audio",
        }
        payload = self._post("/Playlists", params=params)
        playlist_id = payload.get("Id")
        if not playlist_id:
            raise RuntimeError(f"Playlist creation for '{playlist_name}' did not return an Id.")
        return str(playlist_id)

    def delete_playlist(self, playlist_id: str) -> None:
        self._delete(f"/Items/{playlist_id}")

    def _get(self, path: str, params: dict[str, str]) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("GET %s?%s", url, urlencode(params))
        return self._request_json("GET", url, params=params)

    def _post(self, path: str, params: dict[str, str]) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("POST %s?%s", url, urlencode(params))
        return self._request_json("POST", url, params=params)

    def _delete(self, path: str) -> None:
        url = f"{self.base_url}{path}"
        logger.debug("DELETE %s", url)
        self._request_no_content("DELETE", url)

    def _request_json(self, method: str, url: str, params: dict[str, str]) -> dict:
        response = self._request(method, url, params=params)
        if not response.content:
            return {}
        return response.json()

    def _request_no_content(self, method: str, url: str) -> None:
        self._request(method, url, params=None)

    def _request(self, method: str, url: str, params: dict[str, str] | None) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds, headers=self.default_headers) as client:
                    response = client.request(method, url, params=params)
                    response.raise_for_status()
                    return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                should_retry = attempt < self.max_retries and _is_retryable_http_error(exc)
                logger.warning(
                    "service=jellyfin method=%s url=%s attempt=%s retry=%s error=%s",
                    method,
                    url,
                    attempt + 1,
                    should_retry,
                    exc,
                )
                if not should_retry:
                    break
                time.sleep(self.retry_backoff_seconds * (attempt + 1))

        raise RuntimeError(f"service=jellyfin method={method} url={url} message=request_failed error={last_error}")

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
        return JellyfinTrack(
            id=item["Id"],
            name=item.get("Name", ""),
            artists=item.get("Artists") or [],
            album=item.get("Album"),
            path=item.get("Path"),
            index_number=item.get("IndexNumber"),
            parent_index_number=item.get("ParentIndexNumber"),
            provider_ids=item.get("ProviderIds") or {},
        )


def _is_retryable_http_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False
