"""Background playlist-refresh runner with line streaming.

A single ``run-topsongs`` subprocess at a time (the run lock enforces that too),
its stdout fanned out to any number of Server-Sent-Events subscribers, plus a
parser for the ``last_run.txt`` summary the run writes.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..i18n import t

# Numeric fields in last_run.txt; everything else is kept as a string.
_INT_FIELDS = {
    "user_count_seen",
    "targeted_user_count",
    "artist_count_seen",
    "eligible_artist_count",
    "created_playlist_count",
    "replaced_playlist_count",
    "orphan_deleted_count",
    "failed_user_count",
    "failed_artist_count",
    "unmatched_local_track_count",
    "duplicate_local_track_count",
}


class RunActiveError(RuntimeError):
    """Raised when a refresh is requested while one is already running."""


def _resolve_run_cmd() -> list[str]:
    """The argv that launches a playlist refresh, however topsongs is installed."""
    exe = shutil.which("run-topsongs")
    if exe:
        return [exe]
    return [sys.executable, "-c", "import sys; from topsongs.cli import main; sys.exit(main())"]


def parse_last_run(state_dir: Path) -> dict | None:
    """Parse ``state_dir/last_run.txt`` into a dict, or None if it does not exist."""
    path = state_dir / "last_run.txt"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    summary: dict[str, object] = {}
    for line in text.splitlines():
        # The track-detail blocks ("unmatched_local_tracks:", "- ...") are not
        # key=value; stop collecting scalars once we hit them.
        if "=" not in line or line.startswith("-") or line.endswith(":"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        summary[key] = int(value) if key in _INT_FIELDS and value.lstrip("-").isdigit() else value
    return summary or None


class RunManager:
    """Owns the at-most-one active refresh subprocess and broadcasts its output."""

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir
        self._proc: asyncio.subprocess.Process | None = None
        self._lines: list[str] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.return_code: int | None = None
        self.dry_run: bool = False

    @property
    def running(self) -> bool:
        return self._proc is not None and self.return_code is None

    def status(self) -> dict:
        return {
            "running": self.running,
            "dry_run": self.dry_run,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "return_code": self.return_code,
            "line_count": len(self._lines),
        }

    async def start(self, dry_run: bool) -> None:
        async with self._lock:
            if self.running:
                raise RunActiveError(t("A playlist refresh is already running."))
            self._lines = []
            self.return_code = None
            self.finished_at = None
            self.started_at = datetime.now(timezone.utc)
            self.dry_run = dry_run
            env = dict(os.environ, DRY_RUN="true" if dry_run else "false")
            self._proc = await asyncio.create_subprocess_exec(
                *_resolve_run_cmd(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        async for raw in self._proc.stdout:
            self._emit(raw.decode("utf-8", errors="replace").rstrip("\n"))
        self.return_code = await self._proc.wait()
        self.finished_at = datetime.now(timezone.utc)
        self._emit(None)  # sentinel: stream complete

    def _emit(self, line: str | None) -> None:
        if line is not None:
            self._lines.append(line)
        for queue in list(self._subscribers):
            queue.put_nowait(line)

    async def subscribe(self):
        """Yield the backlog then every live line, ending with None when done.

        Snapshotting the backlog and registering the queue happen with no
        ``await`` between them, so on the single-threaded event loop no line can
        slip through the gap — the subscriber sees each line exactly once.
        """
        queue: asyncio.Queue = asyncio.Queue()
        for line in self._lines:
            queue.put_nowait(line)
        if not self.running:
            queue.put_nowait(None)
        self._subscribers.add(queue)
        try:
            while True:
                item = await queue.get()
                yield item
                if item is None:
                    break
        finally:
            self._subscribers.discard(queue)

    def summary(self) -> dict | None:
        return parse_last_run(self._state_dir)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None
