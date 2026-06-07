#!/usr/bin/env python3
"""restart.py — pull the latest source and rebuild/restart the topsongs container.

Reads PROJECT_ROOT from the adjacent .env, runs `git pull` in that source tree,
then `docker compose down` followed by `up -d --build` in this deploy dir. Run
from the deploy dir (next to docker-compose.yml).

Usage: ./restart.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent
ENV_PATH = RUNTIME_DIR / ".env"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def run(command: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    env_values = load_env_file(ENV_PATH)
    project_root = env_values.get("PROJECT_ROOT", "..").strip()
    project_dir = (RUNTIME_DIR / project_root).resolve()

    if not project_dir.exists():
        print(f"PROJECT_ROOT existiert nicht: {project_dir}", file=sys.stderr)
        return 1

    run(["git", "pull"], cwd=project_dir)
    run(["docker", "compose", "down"], cwd=RUNTIME_DIR)
    run(["docker", "compose", "up", "-d", "--build"], cwd=RUNTIME_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
