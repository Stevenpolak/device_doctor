"""Base entity for Device Doctor."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeviceDoctorCoordinator


class DeviceDoctorEntity(CoordinatorEntity[DeviceDoctorCoordinator]):
    """Common base for Device Doctor entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DeviceDoctorCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Device Doctor",
            entry_type=DeviceEntryType.SERVICE,
        )
