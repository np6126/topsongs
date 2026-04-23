from __future__ import annotations

import re
import unicodedata

STRIP_PATTERNS = [
    r"\(.*?remaster.*?\)",
    r"\[.*?remaster.*?\]",
    r"\(.*?live.*?\)",
    r"\[.*?live.*?\]",
    r"\(feat\.? .*?\)",
    r"\[feat\.? .*?\]",
    r"\(ft\.? .*?\)",
    r"\[ft\.? .*?\]",
    r"\s-\sremaster(?:ed)?(?:\s\d+)?",
    r"\s-\slive.*$",
    r"\s-\sradio edit$",
    r"\s-\sedit$",
    r"\s-\sversion$",
]


def ascii_fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_name(value: str) -> str:
    text = ascii_fold(value).lower().strip()
    for pattern in STRIP_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
