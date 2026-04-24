from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    jellyfin_url: str = Field(alias="JELLYFIN_URL")
    jellyfin_api_key: str = Field(alias="JELLYFIN_API_KEY")
    lastfm_api_key: str = Field(alias="LASTFM_API_KEY")

    min_tracks_per_artist: int = Field(default=10, alias="MIN_TRACKS_PER_ARTIST")
    state_dir: Path = Field(default=Path("/app/state"), alias="STATE_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    request_timeout_seconds: float = Field(default=20.0, alias="REQUEST_TIMEOUT_SECONDS")
    request_max_retries: int = Field(default=2, alias="REQUEST_MAX_RETRIES")
    retry_backoff_seconds: float = Field(default=1.0, alias="RETRY_BACKOFF_SECONDS")
    max_provider_tracks: int = Field(default=200, alias="MAX_PROVIDER_TRACKS")
    playlist_name_prefix: str = Field(default="Top Songs - ", alias="PLAYLIST_NAME_PREFIX")

    artist_allowlist: CsvList = Field(default_factory=list, alias="ARTIST_ALLOWLIST")
    artist_denylist: CsvList = Field(default_factory=list, alias="ARTIST_DENYLIST")
    user_allowlist: CsvList = Field(default_factory=list, alias="USER_ALLOWLIST")
    user_denylist: CsvList = Field(default_factory=list, alias="USER_DENYLIST")
    library_path_allowlist: CsvList = Field(default_factory=list, alias="LIBRARY_PATH_ALLOWLIST")
    library_path_denylist: CsvList = Field(default_factory=list, alias="LIBRARY_PATH_DENYLIST")

    @field_validator(
        "artist_allowlist",
        "artist_denylist",
        "user_allowlist",
        "user_denylist",
        "library_path_allowlist",
        "library_path_denylist",
        mode="before",
    )
    @classmethod
    def split_csv(cls, value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]

    @field_validator("jellyfin_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")
