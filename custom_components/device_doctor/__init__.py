"""Device Doctor: finds dead devices and silently failing integrations."""

from __future__ import annotations

from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ALWAYS,
    CONF_IGNORED_DEVICES,
    CONF_IGNORED_ENTRIES,
    DOMAIN,
    KIND_DEVICE,
    KIND_ENTRY,
)
from .coordinator import DeviceDoctorConfigEntry, DeviceDoctorCoordinator
from .rules import async_set_rule
from .services import async_setup_services

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions once, independent of the config entry."""
    async_setup_services(hass)
    return True


async def async_migrate_entry(
    hass: HomeAssistant, entry: DeviceDoctorConfigEntry
) -> bool:
    """Move 0.4's ignored entries and devices into "always" rules."""
    if entry.version == 1 and entry.minor_version < 2:
        options = dict(entry.options)
        for kind, key in (
            (KIND_ENTRY, CONF_IGNORED_ENTRIES),
            (KIND_DEVICE, CONF_IGNORED_DEVICES),
        ):
            for target_id in options.pop(key, []):
                await async_set_rule(hass, entry, kind, target_id, ALWAYS)
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: DeviceDoctorConfigEntry
) -> bool:
    """Set up Device Doctor from a config entry."""
    coordinator = DeviceDoctorCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.settings = _settings(entry)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: DeviceDoctorConfigEntry
) -> bool:
    """Unload a config entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_unload()
    return unloaded


async def _async_update_listener(
    hass: HomeAssistant, entry: DeviceDoctorConfigEntry
) -> None:
    """Reload when the options or rules change, but not for a new rule title."""
    if _settings(entry) != entry.runtime_data.settings:
        await hass.config_entries.async_reload(entry.entry_id)


def _settings(entry: DeviceDoctorConfigEntry) -> tuple[Any, ...]:
    """Return what Device Doctor's behaviour depends on: options and rule data."""
    return (
        sorted(entry.options.items(), key=str),
        sorted(
            (sub.subentry_id, sorted(sub.data.items()))
            for sub in entry.subentries.values()
        ),
    )
