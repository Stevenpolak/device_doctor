"""Checks for translations/*.json.

Mirrors the rules Hassfest applies to translation strings, so a mistake shows
up here instead of in CI: placeholders must be plain {names} (no ICU plural or
select), no placeholders in single quotes, no HTML, no URLs, no leading or
trailing spaces. Other languages must use the same keys and placeholders as
English.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import string
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

# From Home Assistant's script/hassfest/translations.py
RE_PLACEHOLDER_IN_SINGLE_QUOTES = re.compile(r"'{\w+}'")
RE_HTML = re.compile(r"<[a-z/][^>]*>", re.IGNORECASE)
RE_URL = re.compile(r"\w+://|www\.", re.IGNORECASE)


def placeholders(text: str) -> set[str]:
    """Return the placeholder names, failing like Hassfest on anything else."""
    names = set()
    for _, field_name, _, _ in string.Formatter().parse(text):
        if field_name is not None:
            if not field_name.isidentifier():
                raise ValueError(f"placeholder {field_name!r} is not a plain name")
            names.add(field_name)
    return names


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


def load(language: str) -> dict[str, str]:
    return flatten(
        json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    )


def test_rule_catches_icu_plurals() -> None:
    """Hassfest rejects ICU plural/select; so does our check."""
    assert placeholders("{bad} of {total}") == {"bad", "total"}
    with pytest.raises(ValueError):
        placeholders("{total, plural, one {# entity} other {# entities}}")


@pytest.mark.parametrize("language", LANGUAGES)
def test_strings_pass_hassfest_rules(language: str) -> None:
    """Every string would pass Hassfest."""
    for path, text in load(language).items():
        where = f"{language}: {path}"
        try:
            placeholders(text)
        except ValueError as err:
            pytest.fail(f"{where}: {err}")
        assert not RE_PLACEHOLDER_IN_SINGLE_QUOTES.search(text), f"{where}: '{{x}}'"
        assert not RE_HTML.search(text), f"{where}: HTML"
        assert not RE_URL.search(text), f"{where}: URL (use a placeholder)"
        assert text == text.strip(), f"{where}: leading or trailing spaces"


@pytest.mark.parametrize("language", [lang for lang in LANGUAGES if lang != "en"])
def test_language_matches_english(language: str) -> None:
    """No unknown keys, and the same placeholders as English."""
    english = flatten(EN)
    for path, text in load(language).items():
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
