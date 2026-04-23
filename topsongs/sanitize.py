from __future__ import annotations

import re
import unicodedata

MAX_PROVIDER_TRACKS = 200
MAX_TITLE_LENGTH = 200

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def sanitize_untrusted_text(value: str, max_length: int = MAX_TITLE_LENGTH) -> str:
    text = ANSI_ESCAPE_RE.sub("", value)
    text = "".join(ch if _is_safe_char(ch) else " " for ch in text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length].rstrip()


def _is_safe_char(ch: str) -> bool:
    if ch in {"\n", "\r", "\t"}:
        return False
    category = unicodedata.category(ch)
    return not category.startswith("C")
