"""Scan-now button for Device Doctor."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DeviceDoctorConfigEntry
from .entity import DeviceDoctorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceDoctorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([ScanNowButton(entry.runtime_data, "scan_now")])


class ScanNowButton(DeviceDoctorEntity, ButtonEntity):
    """Run a scan immediately instead of waiting for the next interval."""

    _attr_icon = "mdi:magnify-scan"
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Scan now."""
        await self.coordinator.async_refresh()
