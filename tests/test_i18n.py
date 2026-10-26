import ast
import json
import re
import string
from datetime import date
from pathlib import Path

import pytest
from fakes import JellyfinStub, user, wire_cli

from topsongs import i18n, prune_cli, purge_cli
from topsongs.locale_de import GERMAN
from topsongs.models import JellyfinPlaylist

PACKAGE = Path(i18n.__file__).parent


# How many leading arguments of each call are messages: t(message), tn(one, other, count).
_MESSAGE_ARGS = {"t": 1, "tn": 2}


def _messages() -> dict[str, str]:
    """Every literal passed to t() or tn() in the package, with where it is used."""
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name == "i18n.py":  # defines t() and tn()
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            name = getattr(node.func, "id", None) if isinstance(node, ast.Call) else None
            if name in _MESSAGE_ARGS:
                where = f"{path.relative_to(PACKAGE)}:{node.lineno}"
                for arg in node.args[: _MESSAGE_ARGS[name]]:
                    assert isinstance(arg, ast.Constant), f"{where}: {name}() needs literals"
                    found.setdefault(arg.value, where)
    return found


def _fields(template: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(template) if field}


def test_every_message_has_a_german_version():
    missing = {where: message for message, where in _messages().items() if message not in GERMAN}
    assert missing == {}


def test_catalog_has_no_unused_entries():
    assert set(GERMAN) - set(_messages()) == set()


def test_both_versions_use_the_same_placeholders():
    differ = {m: g for m, g in GERMAN.items() if _fields(m) != _fields(g)}
    assert differ == {}


def test_english_keeps_the_message_and_fills_it_in():
    i18n.set_language("en")
    assert i18n.t("{count} deleted", count=3) == "3 deleted"
    assert i18n.fmt_date(date(2026, 10, 12)) == "2026-10-12"

    i18n.set_language("de")
    assert i18n.t("{count} deleted", count=3) == "3 gelöscht"
    assert i18n.fmt_date(date(2026, 10, 12)) == "12.10.2026"


@pytest.mark.parametrize(
    "language,count,expected",
    [
        ("en", 1, "1 playlist"),
        ("en", 0, "0 playlists"),
        ("en", 2, "2 playlists"),
        ("de", 1, "1 Playlist"),
        ("de", 2, "2 Playlists"),
    ],
)
def test_tn_takes_the_singular_for_exactly_one(language, count, expected):
    i18n.set_language(language)
    assert i18n.tn("{count} playlist", "{count} playlists", count) == expected


def test_one_playlist_of_one_user_reads_singular(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TOPSONGS_LANGUAGE", "en")
    nightly = JellyfinPlaylist(id="a1", name="Metallica", tags=["topsongs"])
    jellyfin = JellyfinStub(users=[user("alice")], playlists={"alice": [nightly]})
    wire_cli(monkeypatch, purge_cli, tmp_path, jellyfin)

    assert purge_cli.main(["--dry-run"]) == 0

    out = " ".join(capsys.readouterr().out.split())
    assert "Found 1 playlist with tag 'topsongs' across 1 user." in out
    assert "1 playlist would be deleted." in out


def test_cli_follows_topsongs_language(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TOPSONGS_LANGUAGE", "en")
    wire_cli(monkeypatch, prune_cli, tmp_path, JellyfinStub(users=[user("alice")]))

    assert prune_cli.main(["--keep", "Mine", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "Dry run:" in out and "Nothing changed." in out
    assert "Dry-Run" not in out


# --------------------------------------------------------------------------- #
# Web dashboard: app.js t() calls and index.html texts against static/de.json
# --------------------------------------------------------------------------- #

STATIC = PACKAGE / "web" / "static"
_JS_STRING = r"([\"'])((?:\\.|(?!{q}).)*){q}"
_JS_CALL = re.compile(r"\bt\(\s*" + _JS_STRING.format(q=r"\1"))
_JS_PLURAL = re.compile(
    r"\btn\(\s*" + _JS_STRING.format(q=r"\1") + r"\s*,\s*" + _JS_STRING.format(q=r"\3")
)
_JS_NON_LITERAL = re.compile(r"\btn?\(\s*[^\"'\s)]")  # "t()" alone is prose in a comment
_HTML_TEXT = re.compile(r"<(\w+)\b[^>]*\bdata-i18n\b[^>]*>(.*?)</\1>", re.DOTALL)
_HTML_ATTR = re.compile(r"\s(?:placeholder|title)=\"([^\"]*)\"")


def _web_messages() -> set[str]:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert not _JS_NON_LITERAL.findall(script), "app.js: t() and tn() need literals"
    texts = {" ".join(text.split()) for _, text in _HTML_TEXT.findall(page)}
    plurals = {m for _, one, _, other in _JS_PLURAL.findall(script) for m in (one, other)}
    calls = {m for _, m in _JS_CALL.findall(script)}
    return calls | plurals | texts | set(_HTML_ATTR.findall(page))


def _web_catalog() -> dict[str, str]:
    return json.loads((STATIC / "de.json").read_text(encoding="utf-8"))


def test_web_catalog_covers_every_text():
    assert _web_messages() - set(_web_catalog()) == set()


def test_web_catalog_has_no_unused_entries():
    assert set(_web_catalog()) - _web_messages() == set()


def test_web_catalog_keeps_the_placeholders():
    differ = {m: g for m, g in _web_catalog().items() if _fields(m) != _fields(g)}
    assert differ == {}
