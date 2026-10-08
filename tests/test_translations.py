"""Checks for translations/*.json.

Home Assistant formats these strings with ICU MessageFormat, so a missing
brace or an unknown placeholder only shows up as a broken text in the UI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

TRANSLATIONS = (
    Path(__file__).parent.parent
    / "custom_components"
    / "device_doctor"
    / "translations"
)
EN = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
LANGUAGES = sorted(path.stem for path in TRANSLATIONS.glob("*.json"))
PLURAL_FORMS = {"zero", "one", "two", "few", "many", "other"}


class ICUError(ValueError):
    """The string is not valid ICU MessageFormat."""


def placeholders(message: str) -> set[str]:
    """Return the argument names used in an ICU message."""
    names: set[str] = set()
    end = _message(message, 0, names, top=True)
    if end != len(message):
        raise ICUError(f"unexpected '}}' at {end}")
    return names


def _message(text: str, pos: int, names: set[str], top: bool = False) -> int:
    """Parse text up to an unmatched '}' (or the end); return its position."""
    while pos < len(text):
        char = text[pos]
        if char == "{":
            pos = _argument(text, pos + 1, names)
        elif char == "}":
            if top:
                raise ICUError(f"unexpected '}}' at {pos}")
            return pos
        else:
            pos += 1
    if not top:
        raise ICUError("missing '}'")
    return pos


def _argument(text: str, pos: int, names: set[str]) -> int:
    """Parse '{name}' or '{name, type, options}'; pos is just after '{'."""
    end = _find(text, pos, ",}")
    name = text[pos:end].strip()
    if not name.isidentifier():
        raise ICUError(f"bad argument name {name!r}")
    names.add(name)
    if text[end] == "}":
        return end + 1

    type_end = _find(text, end + 1, ",}")
    arg_type = text[end + 1 : type_end].strip()
    if arg_type not in ("plural", "select", "selectordinal"):
        raise ICUError(f"unsupported argument type {arg_type!r}")
    if text[type_end] != ",":
        raise ICUError(f"{arg_type} without options")

    pos, keys = type_end + 1, set()
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            raise ICUError("missing '}'")
        if text[pos] == "}":
            break
        key_end = _find(text, pos, "{")
        key = text[pos:key_end].strip()
        if not key or " " in key:
            raise ICUError(f"bad option key {key!r}")
        if arg_type != "select" and key not in PLURAL_FORMS and not key.startswith("="):
            raise ICUError(f"unknown plural form {key!r}")
        keys.add(key)
        pos = _message(text, key_end + 1, names) + 1
    if "other" not in keys:
        raise ICUError(f"{arg_type} for {name!r} has no 'other'")
    return pos + 1


def _find(text: str, pos: int, chars: str) -> int:
    while pos < len(text) and text[pos] not in chars:
        pos += 1
    if pos >= len(text):
        raise ICUError("missing '}'")
    return pos


def flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Return {"a.b.c": "text"} for every string."""
    flat: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{path}."))
        else:
            flat[path] = value
    return flat


def test_parser_catches_mistakes() -> None:
    """Sanity-check the parser itself."""
    assert placeholders("{a} of {b, plural, one {# x} other {# xs}}") == {"a", "b"}
    assert placeholders("{s, select, yes {Error: {r}} other {}}") == {"s", "r"}
    for broken in ("{a", "a}", "{n, plural, one {x}}", "{n, plural, few {x} other {y}"):
        with pytest.raises(ICUError):
            placeholders(broken)


@pytest.mark.parametrize("language", LANGUAGES)
def test_strings_are_valid_icu(language: str) -> None:
    """Every string parses, and plurals/selects have an 'other' case."""
    data = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    for path, text in flatten(data).items():
        try:
            placeholders(text)
        except ICUError as err:
            pytest.fail(f"{language}: {path}: {err}")


@pytest.mark.parametrize("language", [lang for lang in LANGUAGES if lang != "en"])
def test_language_matches_english(language: str) -> None:
    """No unknown keys, and the same placeholders as English."""
    english = flatten(EN)
    data = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    for path, text in flatten(data).items():
        assert path in english, f"{language}: {path} does not exist in en.json"
        assert placeholders(text) == placeholders(english[path]), (
            f"{language}: {path} uses different placeholders than English"
        )


def test_setup_and_options_forms_match() -> None:
    """The setup form and the options form show the same sections."""
    assert (
        EN["config"]["step"]["user"]["sections"]
        == EN["options"]["step"]["init"]["sections"]
    )
