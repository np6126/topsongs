from __future__ import annotations

import re
import unicodedata

# Parenthesized/bracketed tags that mark an alternate take of the *same song*
# (a different version, format, or mix). Stripping them lets an alt-version
# title normalize onto its base title so duplicates collapse and lone alt
# versions still match the provider's studio rank.
_ALT_VERSION_TAGS = (
    r"[^()\[\]]*version",
    r"orchestral[^()\[\]]*",
    r"acoustic[^()\[\]]*",
    r"demo[^()\[\]]*",
    r"instrumental[^()\[\]]*",
    r"[^()\[\]]*remix",
    r"[^()\[\]]*\bmix",
    r"[^()\[\]]*\bedit",
    r"bonus track[^()\[\]]*",
    r"re-?recorded[^()\[\]]*",
    r"reprise",
)

STRIP_PATTERNS = [
    r"\(.*?remaster.*?\)",
    r"\[.*?remaster.*?\]",
    r"\(.*?live.*?\)",
    r"\[.*?live.*?\]",
    r"\(feat\.? .*?\)",
    r"\[feat\.? .*?\]",
    r"\(ft\.? .*?\)",
    r"\[ft\.? .*?\]",
    *[rf"\((?:{tag})\)" for tag in _ALT_VERSION_TAGS],
    *[rf"\[(?:{tag})\]" for tag in _ALT_VERSION_TAGS],
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
