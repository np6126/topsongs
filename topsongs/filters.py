from __future__ import annotations

from collections.abc import Iterable

from .models import JellyfinTrack, JellyfinUser
from .normalize import normalize_name


class NameFilter:
    def __init__(self, allowlist: Iterable[str], denylist: Iterable[str]) -> None:
        self._allowlist = {normalize_name(item) for item in allowlist}
        self._denylist = {normalize_name(item) for item in denylist}

    def matches(self, name: str) -> bool:
        normalized = normalize_name(name)

        if self._allowlist and normalized not in self._allowlist:
            return False

        return normalized not in self._denylist


class UserFilter:
    def __init__(self, allowlist: Iterable[str], denylist: Iterable[str]) -> None:
        self._name_filter = NameFilter(allowlist, denylist)

    def matches(self, user: JellyfinUser) -> bool:
        return self._name_filter.matches(user.name) and not user.policy.is_disabled


class LibraryPathFilter:
    def __init__(self, allowlist: Iterable[str], denylist: Iterable[str]) -> None:
        self._allowlist = [self._normalize_path_prefix(item) for item in allowlist]
        self._denylist = [self._normalize_path_prefix(item) for item in denylist]

    def filter_tracks(self, tracks: Iterable[JellyfinTrack]) -> list[JellyfinTrack]:
        return [track for track in tracks if self.matches(track.path)]

    def matches(self, path: str | None) -> bool:
        normalized_path = self._normalize_track_path(path)

        if self._allowlist:
            if normalized_path is None:
                return False
            if not any(
                self._path_matches_prefix(normalized_path, prefix)
                for prefix in self._allowlist
            ):
                return False

        if self._denylist:
            if normalized_path is not None and any(
                self._path_matches_prefix(normalized_path, prefix)
                for prefix in self._denylist
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
