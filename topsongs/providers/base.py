from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import ProviderTrack


class TopSongsProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_top_tracks(self, artist_name: str) -> list[ProviderTrack]:
        raise NotImplementedError
