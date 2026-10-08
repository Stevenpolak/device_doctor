"""Allowed-offline rules, stored as config subentries of the Device Doctor entry.

A rule says how long one integration entry or one device may be offline before
Device Doctor raises a repair. The duration "always" is what "Ignore" does.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import (
    ALLOWED_OFFLINE_SECONDS,
    KIND_DEVICE,
    RULE_ALLOWED_OFFLINE,
    RULE_TARGET_ID,
    RULE_TARGET_KIND,
    SUBENTRY_ALLOWED_OFFLINE,
)


@dataclass(frozen=True, slots=True)
class Rule:
    """How long one integration entry or device may be offline."""

    kind: str
    target_id: str
    seconds: int | None  # None: always allowed, i.e. ignored

    @property
    def always(self) -> bool:
        """Return True for an ignore rule."""
        return self.seconds is None


def rule_unique_id(kind: str, target_id: str) -> str:
    """Return the subentry unique id, so each target has at most one rule."""
    return f"{kind}_{target_id}"


@callback
def async_get_rules(entry: ConfigEntry) -> dict[tuple[str, str], Rule]:
    """Return the rules of the Device Doctor entry, keyed by (kind, target id)."""
    rules: dict[tuple[str, str], Rule] = {}
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_ALLOWED_OFFLINE:
            continue
        allowed = subentry.data.get(RULE_ALLOWED_OFFLINE)
        if allowed not in ALLOWED_OFFLINE_SECONDS:
            continue
        kind, target_id = subentry.data[RULE_TARGET_KIND], subentry.data[RULE_TARGET_ID]
        rules[kind, target_id] = Rule(kind, target_id, ALLOWED_OFFLINE_SECONDS[allowed])
    return rules


@callback
def async_set_rule(
    hass: HomeAssistant,
    entry: ConfigEntry,
    kind: str,
    target_id: str,
    allowed: str,
) -> None:
    """Add a rule, or change the duration of the existing rule for this target."""
    data = {
        RULE_TARGET_KIND: kind,
        RULE_TARGET_ID: target_id,
        RULE_ALLOWED_OFFLINE: allowed,
    }
    title = async_target_title(hass, kind, target_id)
    unique_id = rule_unique_id(kind, target_id)
    for subentry in entry.subentries.values():
        if (
            subentry.subentry_type == SUBENTRY_ALLOWED_OFFLINE
            and subentry.unique_id == unique_id
        ):
            hass.config_entries.async_update_subentry(
                entry, subentry, data=data, title=title
            )
            return
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type=SUBENTRY_ALLOWED_OFFLINE,
            title=title,
            unique_id=unique_id,
        ),
    )


@callback
def async_target_title(hass: HomeAssistant, kind: str, target_id: str) -> str:
    """Return a readable name for a rule's target."""
    if kind == KIND_DEVICE:
        if device := dr.async_get(hass).async_get(target_id):
            return device.name_by_user or device.name or target_id
        return target_id
    if entry := hass.config_entries.async_get_entry(target_id):
        return f"{entry.title or entry.domain} ({entry.domain})"
    return target_id
