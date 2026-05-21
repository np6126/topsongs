from __future__ import annotations

import logging


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )
    # httpx logs every request at INFO. The Jellyfin and Last.fm clients already
    # log their own requests at DEBUG, so keep only httpx warnings and errors.
    logging.getLogger("httpx").setLevel(logging.WARNING)
