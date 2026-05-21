from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CsvList = Annotated[list[str], NoDecode]

# Resolve appdata/.env relative to the repository so `topsongs` finds the same
# config file regardless of the working directory it is invoked from. In the
# container the package is installed elsewhere and this path does not exist;
# config there comes from environment variables exported by the entrypoint.
_ENV_FILE = Path(__file__).resolve().parent.parent / "appdata" / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    jellyfin_url: str = Field(alias="JELLYFIN_URL")
    jellyfin_api_key: str = Field(alias="JELLYFIN_API_KEY")
    lastfm_api_key: str = Field(alias="LASTFM_API_KEY")

    min_tracks_per_artist: int = Field(default=10, alias="MIN_TRACKS_PER_ARTIST")
    min_track_duration_seconds: int = Field(default=60, alias="MIN_TRACK_DURATION_SECONDS")
    state_dir: Path = Field(default=Path("state"), alias="STATE_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    request_timeout_seconds: float = Field(default=20.0, alias="REQUEST_TIMEOUT_SECONDS")
    request_max_retries: int = Field(default=2, alias="REQUEST_MAX_RETRIES")
    retry_backoff_seconds: float = Field(default=1.0, alias="RETRY_BACKOFF_SECONDS")
    run_concurrency: int = Field(default=1, alias="RUN_CONCURRENCY")
    min_request_interval: float = Field(default=0.0, alias="MIN_REQUEST_INTERVAL")
    max_provider_tracks: int = Field(default=200, alias="MAX_PROVIDER_TRACKS")
    personalization_weight: float = Field(default=0.6, alias="PERSONALIZATION_WEIGHT")
    playlist_name_prefix: str = Field(default="Top Songs - ", alias="PLAYLIST_NAME_PREFIX")
    append_unmatched_songs: bool = Field(default=True, alias="APPEND_UNMATCHED_SONGS")
    dry_run: bool = Field(default=False, alias="DRY_RUN")

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

    @field_validator("personalization_weight")
    @classmethod
    def clamp_personalization_weight(cls, value: float) -> float:
        return min(1.0, max(0.0, value))

    @field_validator("run_concurrency")
    @classmethod
    def clamp_run_concurrency(cls, value: int) -> int:
        # Lower bound 1: ThreadPoolExecutor(max_workers=0) raises, and 1 keeps
        # the sequential default. Upper bound 16: a typo must not flood the
        # homeserver with worker threads.
        return min(16, max(1, value))

    @field_validator("min_request_interval")
    @classmethod
    def clamp_min_request_interval(cls, value: float) -> float:
        return max(0.0, value)
