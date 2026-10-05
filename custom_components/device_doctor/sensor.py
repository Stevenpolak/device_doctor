"""Problem count sensor for Device Doctor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DeviceDoctorConfigEntry
from .entity import DeviceDoctorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceDoctorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor."""
    async_add_entities([ProblemCountSensor(entry.runtime_data, "problems")])


class ProblemCountSensor(DeviceDoctorEntity, SensorEntity):
    """Number of confirmed problems, with the details as attributes."""

    _attr_icon = "mdi:stethoscope"
    _attr_state_class = SensorStateClass.MEASUREMENT
    # The problem list can be long and changes often; keep it out of history.
    _unrecorded_attributes = frozenset({"problems"})

    @property
    def native_value(self) -> int:
        """Return the number of confirmed problems."""
        return len(self.coordinator.data.confirmed)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the problem details."""
        data = self.coordinator.data
        return {
            "problems": [problem.as_dict() for problem in data.confirmed.values()],
            "unconfirmed": len(data.candidates) - len(data.confirmed),
        }
