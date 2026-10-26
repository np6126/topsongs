"""Texts a person reads, in TOPSONGS_LANGUAGE: English or German.

The code writes each message in English and passes it through t(); GERMAN in
locale_de.py holds the German version. Placeholders like {name} are filled in
after the lookup, so both versions use the same names. Logs stay English.
"""
from __future__ import annotations

from datetime import date

from .locale_de import GERMAN

_language = "en"


def set_language(language: str) -> None:
    global _language
    _language = language


def language() -> str:
    return _language


def use_configured_language() -> None:
    """Switch to TOPSONGS_LANGUAGE, read on its own so --help works unconfigured."""
    from .config import LanguageSettings

    set_language(LanguageSettings().language)


def t(message: str, **values: object) -> str:
    template = GERMAN.get(message, message) if _language == "de" else message
    return template.format(**values) if values else template


def tn(one: str, other: str, count: int, **values: object) -> str:
    """t() for a counted message: `one` when count is 1, else `other`; {count} is filled in."""
    return t(one if count == 1 else other, count=count, **values)


def fmt_date(day: date | None) -> str:
    if day is None:
        return "—"
    return day.strftime("%d.%m.%Y" if _language == "de" else "%Y-%m-%d")
