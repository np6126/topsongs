import ast
import json
import re
import string
from datetime import date
from pathlib import Path

from fakes import JellyfinStub, user, wire_cli

from topsongs import i18n, prune_cli
from topsongs.locale_de import GERMAN

PACKAGE = Path(i18n.__file__).parent


def _messages() -> dict[str, str]:
    """Every literal passed to t() in the package, with where it is used."""
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "t":
                where = f"{path.relative_to(PACKAGE)}:{node.lineno}"
                arg = node.args[0]
                assert isinstance(arg, ast.Constant), f"{where}: t() needs a literal"
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
_JS_CALL = re.compile(r"\bt\(\s*([\"'])((?:\\.|(?!\1).)*)\1")
_JS_NON_LITERAL = re.compile(r"(?<!function )\bt\(\s*[^\"'\s]")
_HTML_TEXT = re.compile(r"<(\w+)\b[^>]*\bdata-i18n\b[^>]*>(.*?)</\1>", re.DOTALL)
_HTML_ATTR = re.compile(r"\s(?:placeholder|title)=\"([^\"]*)\"")


def _web_messages() -> set[str]:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert not _JS_NON_LITERAL.findall(script), "app.js: t() needs a literal"
    texts = {" ".join(text.split()) for _, text in _HTML_TEXT.findall(page)}
    return {m for _, m in _JS_CALL.findall(script)} | texts | set(_HTML_ATTR.findall(page))


def _web_catalog() -> dict[str, str]:
    return json.loads((STATIC / "de.json").read_text(encoding="utf-8"))


def test_web_catalog_covers_every_text():
    assert _web_messages() - set(_web_catalog()) == set()


def test_web_catalog_has_no_unused_entries():
    assert set(_web_catalog()) - _web_messages() == set()


def test_web_catalog_keeps_the_placeholders():
    differ = {m: g for m, g in _web_catalog().items() if _fields(m) != _fields(g)}
    assert differ == {}
