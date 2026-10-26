"""Sensors for Device Doctor."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ALLOWED_OFFLINE_SECONDS, SUBENTRY_IGNORED
from .coordinator import DeviceDoctorConfigEntry, DeviceDoctorCoordinator
from .entity import DeviceDoctorEntity
from .rules import Rule, async_target_device, rule_of

STATUS_OK = "ok"
STATUS_ALLOWED_OFFLINE = "allowed_offline"
STATUS_PROBLEM = "problem"
RULE_OPTIONS = [*ALLOWED_OFFLINE_SECONDS, SUBENTRY_IGNORED]
STATUS_OPTIONS = [STATUS_OK, STATUS_ALLOWED_OFFLINE, STATUS_PROBLEM]


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
    # Each rule shows on its device's own page. Added per subentry, so deleting
    # the rule also deletes its sensors.
    for subentry in entry.subentries.values():
        if (rule := rule_of(subentry)) is None:
            continue
        if (device := async_target_device(hass, rule.kind, rule.target_id)) is None:
            continue  # gone, or an integration without exactly one device
        sensors: list[SensorEntity] = [RuleSensor(coordinator, subentry, rule, device)]
        if not rule.ignored:
            sensors.append(RuleStatusSensor(coordinator, subentry, rule, device))
        async_add_entities(sensors, config_subentry_id=subentry.subentry_id)


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


class RuleEntity(CoordinatorEntity[DeviceDoctorCoordinator], SensorEntity):
    """A rule's sensor, shown on the device the rule is about."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(
        self,
        coordinator: DeviceDoctorCoordinator,
        subentry: ConfigSubentry,
        rule: Rule,
        device: dr.DeviceEntry,
        key: str,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.rule = rule
        self._attr_translation_key = key
        self._attr_unique_id = f"{subentry.subentry_id}_{key}"
        # Attach to the other integration's device without adding Device
        # Doctor to it (no device_info), like HA's own helper integrations.
        self.device_entry = device


class RuleSensor(RuleEntity):
    """What the rule says: ignored, or allowed offline for how long."""

    _attr_options = RULE_OPTIONS

    def __init__(
        self,
        coordinator: DeviceDoctorCoordinator,
        subentry: ConfigSubentry,
        rule: Rule,
        device: dr.DeviceEntry,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, subentry, rule, device, "rule")
        self._attr_native_value = SUBENTRY_IGNORED if rule.ignored else rule.allowed


class RuleStatusSensor(RuleEntity):
    """How Device Doctor sees the device now, for allowed-offline rules."""

    _attr_options = STATUS_OPTIONS

    def __init__(
        self,
        coordinator: DeviceDoctorCoordinator,
        subentry: ConfigSubentry,
        rule: Rule,
        device: dr.DeviceEntry,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, subentry, rule, device, "rule_status")

    @property
    def native_value(self) -> str | None:
        """Return the status, unknown when it wasn't checked (yet)."""
        data = self.coordinator.data
        target_id = self.rule.target_id
        if target_id in data.confirmed:
            return STATUS_PROBLEM
        if target_id in data.offline:
            return STATUS_ALLOWED_OFFLINE
        if target_id in data.healthy:
            return STATUS_OK
        return None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return when it last worked, went offline and is (or was) reported."""
        data = self.coordinator.data
        target_id = self.rule.target_id
        problem = data.confirmed.get(target_id) or data.offline.get(target_id)
        offline_since = problem.since if problem else None
        reported_at = problem.reported_at if problem else None
        # Not reported yet: when the allowed time runs out.
        if (
            reported_at is None
            and self.rule.seconds is not None
            and (since := dt_util.parse_datetime(offline_since or ""))
        ):
            reported_at = (since + timedelta(seconds=self.rule.seconds)).isoformat()
        return {
            "last_ok": self.coordinator.last_ok.get(target_id),
            "offline_since": offline_since,
            "reported_at": reported_at,
        }
