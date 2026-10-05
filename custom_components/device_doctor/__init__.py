"""Device Doctor: finds dead devices and silently failing integrations."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import DeviceDoctorConfigEntry, DeviceDoctorCoordinator
from .services import async_setup_services

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions once, independent of the config entry."""
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: DeviceDoctorConfigEntry
) -> bool:
    """Set up Device Doctor from a config entry."""
    coordinator = DeviceDoctorCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

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
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)
