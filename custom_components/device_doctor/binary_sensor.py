"""Problem binary sensor for Device Doctor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DeviceDoctorConfigEntry
from .entity import DeviceDoctorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceDoctorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor."""
    async_add_entities([ProblemBinarySensor(entry.runtime_data, "problem")])


class ProblemBinarySensor(DeviceDoctorEntity, BinarySensorEntity):
    """On while at least one problem is confirmed."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        """Return true if any problem is confirmed."""
        return bool(self.coordinator.data.confirmed)
