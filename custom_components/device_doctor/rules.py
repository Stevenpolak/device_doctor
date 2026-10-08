"""Rules for single integrations and devices, stored as config subentries.

Two kinds, each its own subentry type so the Device Doctor page labels them:
- "ignored": never checked (what Ignore on a repair does);
- "allowed offline": only reported once offline for longer than a duration.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.translation import async_get_translations
from homeassistant.loader import async_get_loaded_integration

from .const import (
    ALLOWED_OFFLINE_SECONDS,
    DOMAIN,
    IGNORE,
    KIND_DEVICE,
    RULE_ALLOWED_OFFLINE,
    RULE_TARGET_ID,
    RULE_TARGET_KIND,
    SUBENTRY_ALLOWED_OFFLINE,
    SUBENTRY_IGNORED,
)

RULE_TYPES = (SUBENTRY_IGNORED, SUBENTRY_ALLOWED_OFFLINE)


@dataclass(frozen=True, slots=True)
class Rule:
    """How long one integration entry or device may be offline."""

    kind: str
    target_id: str
    seconds: int | None  # None: ignored, never checked

    @property
    def ignored(self) -> bool:
        """Return True for an ignored rule."""
        return self.seconds is None


def rule_unique_id(kind: str, target_id: str) -> str:
    """Return the subentry unique id, so each target has at most one rule."""
    return f"{kind}_{target_id}"


@callback
def async_get_rules(entry: ConfigEntry) -> dict[tuple[str, str], Rule]:
    """Return the rules of the Device Doctor entry, keyed by (kind, target id)."""
    rules: dict[tuple[str, str], Rule] = {}
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_IGNORED:
            seconds = None
        elif subentry.subentry_type == SUBENTRY_ALLOWED_OFFLINE:
            allowed = subentry.data.get(RULE_ALLOWED_OFFLINE)
            if allowed not in ALLOWED_OFFLINE_SECONDS:
                continue
            seconds = ALLOWED_OFFLINE_SECONDS[allowed]
        else:
            continue
        kind, target_id = subentry.data[RULE_TARGET_KIND], subentry.data[RULE_TARGET_ID]
        rules[kind, target_id] = Rule(kind, target_id, seconds)
    return rules


@callback
def async_find_rule(
    entry: ConfigEntry, kind: str, target_id: str
) -> ConfigSubentry | None:
    """Return the rule subentry for a target, of either type."""
    unique_id = rule_unique_id(kind, target_id)
    return next(
        (
            subentry
            for subentry in entry.subentries.values()
            if subentry.subentry_type in RULE_TYPES and subentry.unique_id == unique_id
        ),
        None,
    )


def rule_data(kind: str, target_id: str, allowed: str) -> dict[str, str]:
    """Return the subentry data for a rule; ignored rules have no duration."""
    data = {RULE_TARGET_KIND: kind, RULE_TARGET_ID: target_id}
    if allowed != IGNORE:
        data[RULE_ALLOWED_OFFLINE] = allowed
    return data


async def async_set_rule(
    hass: HomeAssistant,
    entry: ConfigEntry,
    kind: str,
    target_id: str,
    allowed: str,
) -> None:
    """Save a rule: ``allowed`` is a duration key, or IGNORE.

    Replaces an existing rule for the same target, also of the other type.
    """
    subentry_type = SUBENTRY_IGNORED if allowed == IGNORE else SUBENTRY_ALLOWED_OFFLINE
    data = rule_data(kind, target_id, allowed)
    title = await async_rule_title(hass, kind, target_id, allowed)
    if existing := async_find_rule(entry, kind, target_id):
        if existing.subentry_type == subentry_type:
            hass.config_entries.async_update_subentry(
                entry, existing, data=data, title=title
            )
            return
        hass.config_entries.async_remove_subentry(entry, existing.subentry_id)
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type=subentry_type,
            title=title,
            unique_id=rule_unique_id(kind, target_id),
        ),
    )


async def async_refresh_rule_titles(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update rule titles after a device was renamed or moved to another area."""
    for subentry in list(entry.subentries.values()):
        if subentry.subentry_type not in RULE_TYPES:
            continue
        title = await async_rule_title(
            hass,
            subentry.data[RULE_TARGET_KIND],
            subentry.data[RULE_TARGET_ID],
            subentry.data.get(RULE_ALLOWED_OFFLINE, IGNORE),
        )
        if title != subentry.title:
            hass.config_entries.async_update_subentry(entry, subentry, title=title)


# Used when the translations can't be loaded; same as translations/en.json.
DURATION_FALLBACK = {"1d": "1 day", "3d": "3 days", "7d": "1 week", "30d": "30 days"}


async def async_rule_title(
    hass: HomeAssistant, kind: str, target_id: str, allowed: str
) -> str:
    """Return e.g. 'Leak sensor (Hallway)' or 'Inverter (growatt) · 1 day'."""
    name = async_target_title(hass, kind, target_id)
    if allowed == IGNORE:
        return name
    translations = await async_get_translations(
        hass, hass.config.language, "selector", [DOMAIN]
    )
    duration = translations.get(
        f"component.{DOMAIN}.selector.allowed_offline.options.{allowed}",
        DURATION_FALLBACK.get(allowed, allowed),
    )
    return f"{name} · {duration}"


@callback
def async_target_title(hass: HomeAssistant, kind: str, target_id: str) -> str:
    """Return a readable name: the device with its area, or the integration."""
    if kind == KIND_DEVICE:
        device = dr.async_get(hass).async_get(target_id)
        if device is None:
            return target_id
        name = device.name_by_user or device.name or target_id
        if device.area_id and (
            area := ar.async_get(hass).async_get_area(device.area_id)
        ):
            return f"{name} ({area.name})"
        return name
    if (entry := hass.config_entries.async_get_entry(target_id)) is None:
        return target_id
    name = entry.title or entry.domain
    # One device, one name: its device name beats e.g. a serial number title.
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), target_id)
    if len(devices) == 1:
        name = devices[0].name_by_user or devices[0].name or name
    return f"{name} ({integration_name(hass, entry.domain)})"


@callback
def integration_name(hass: HomeAssistant, domain: str) -> str:
    """Return an integration's display name, such as "ESPHome" for esphome."""
    try:
        return async_get_loaded_integration(hass, domain).name
    except Exception:  # noqa: BLE001 - not loaded (e.g. failed setup): use the id
        return domain
