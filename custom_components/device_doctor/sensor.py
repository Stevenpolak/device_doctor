"""Sensors for Device Doctor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
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
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ProblemCountSensor(coordinator, "problems"),
            FaultsTotalSensor(coordinator, "faults_total"),
            SkippedEntitiesSensor(coordinator, "skipped_entities"),
        ]
    )


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


class FaultsTotalSensor(DeviceDoctorEntity, SensorEntity):
    """Problems confirmed since install; only ever goes up."""

    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int:
        """Return the running total."""
        return self.coordinator.faults_total


class SkippedEntitiesSensor(DeviceDoctorEntity, SensorEntity):
    """Entities left out of the checks by the exclusions."""

    _attr_icon = "mdi:eye-off"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | None:
        """Return the number of skipped entities, unknown until the first scan."""
        skipped = self.coordinator.data.skipped
        return None if skipped is None else sum(skipped.values())

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        """Return the count per exclusion type."""
        return self.coordinator.data.skipped or {}
