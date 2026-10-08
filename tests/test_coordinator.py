"""Tests for the Device Doctor scan logic."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.device_doctor.const import (
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_PROBLEM,
    IGNORE,
    KIND_DEVICE,
    KIND_ENTRY,
)
from custom_components.device_doctor.coordinator import DeviceDoctorCoordinator
from custom_components.device_doctor.rules import async_set_rule


@pytest.fixture
async def coordinator(hass: HomeAssistant) -> AsyncGenerator[DeviceDoctorCoordinator]:
    """Return a coordinator with default options."""
    entry = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    coordinator = DeviceDoctorCoordinator(hass, entry)
    yield coordinator
    await coordinator.async_unload()


def add_integration(
    hass: HomeAssistant,
    domain: str,
    states: list[str],
    *,
    devices: int = 0,
    **entry_kwargs,
) -> MockConfigEntry:
    """Add a config entry with one sensor per given state.

    With ``devices``, the sensors are spread round-robin over that many devices.
    """
    entry = MockConfigEntry(domain=domain, title=domain, **entry_kwargs)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    device_ids = [
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(domain, f"device_{i}")},
            name=f"{domain} device {i}",
        ).id
        for i in range(devices)
    ]
    for i, state in enumerate(states):
        reg_entry = ent_reg.async_get_or_create(
            "sensor",
            domain,
            f"{domain}_{i}",
            config_entry=entry,
            device_id=device_ids[i % devices] if devices else None,
        )
        hass.states.async_set(reg_entry.entity_id, state)
    return entry


def entity_id_of(hass: HomeAssistant, domain: str, index: int) -> str:
    """Return the entity id of a test integration's sensor number ``index``."""
    return er.async_get(hass).async_get_entity_id("sensor", domain, f"{domain}_{index}")


def device_id_of(hass: HomeAssistant, domain: str) -> str:
    """Return the id of a test integration's first device, via its first entity."""
    return er.async_get(hass).async_get(entity_id_of(hass, domain, 0)).device_id


async def test_entry_confirmed_after_two_scans(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """A mostly-unavailable entry is a candidate first, then confirmed."""
    entry = add_integration(hass, "p1", [STATE_UNAVAILABLE] * 3 + ["42"])

    await coordinator.async_refresh()
    assert entry.entry_id in coordinator.data.candidates
    assert not coordinator.data.confirmed

    await coordinator.async_refresh()
    problem = coordinator.data.confirmed[entry.entry_id]
    assert (problem.bad, problem.total) == (3, 4)


async def test_blip_is_not_confirmed(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """Something that recovers before the second scan is never raised."""
    entry = add_integration(hass, "flaky", [STATE_UNAVAILABLE])
    await coordinator.async_refresh()

    hass.states.async_set(next(iter(hass.states.async_entity_ids())), "on")
    await coordinator.async_refresh()

    assert entry.entry_id not in coordinator.data.candidates
    assert not coordinator.data.confirmed


async def test_below_threshold_is_ignored(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """Half unavailable is not more than 50%."""
    add_integration(hass, "half", [STATE_UNAVAILABLE, "1"])
    assert coordinator.scan().problems == {}


async def test_failed_entry_without_entities(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """An entry that failed setup is flagged even with no entities."""
    entry = add_integration(hass, "broken", [], state=ConfigEntryState.SETUP_RETRY)
    problem = coordinator.scan().problems[entry.entry_id]
    assert problem.detail == "setup_retry"
    assert problem.issue_key == "entry_retrying"
    assert problem.total == 0


async def test_disabled_ignored_and_skipped_entries(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """Disabled, ignored and excluded integrations are never flagged."""
    add_integration(
        hass, "off", [STATE_UNAVAILABLE], disabled_by=ConfigEntryDisabler.USER
    )
    add_integration(
        hass, "ignored", [], source="ignore", state=ConfigEntryState.SETUP_ERROR
    )
    add_integration(hass, "group", [STATE_UNAVAILABLE])
    assert coordinator.scan().problems == {}


async def test_hub_devices_judged_individually(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """One dead Zigbee device is flagged without flagging the whole hub."""
    # device 0 gets states 0, 2, 4 (all unavailable); device 1 gets 1, 3, 5.
    add_integration(
        hass,
        "zha",
        [STATE_UNAVAILABLE, "1", STATE_UNAVAILABLE, "1", STATE_UNAVAILABLE, "1"],
        devices=2,
    )
    problems = list(coordinator.scan().problems.values())
    assert len(problems) == 1
    assert problems[0].kind == "device"
    assert problems[0].title == "zha device 0"


async def test_hub_down_raises_one_problem(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """When the whole hub is down its devices are not listed separately."""
    entry = add_integration(hass, "zha", [STATE_UNAVAILABLE] * 4, devices=2)
    assert list(coordinator.scan().problems) == [entry.entry_id]


async def test_repair_issue_lifecycle(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """A confirmed problem raises a fixable issue that clears on recovery."""
    entry = add_integration(hass, "p1", [STATE_UNAVAILABLE])
    issue_reg = ir.async_get(hass)
    issue_id = f"entry_{entry.entry_id}"

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    issue = issue_reg.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.is_fixable

    hass.states.async_set(next(iter(hass.states.async_entity_ids())), "1")
    await coordinator.async_refresh()
    assert issue_reg.async_get_issue(DOMAIN, issue_id) is None


async def test_ignored_devices(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """Ignored devices are left out, for hubs and for regular integrations."""
    add_integration(hass, "zha", [STATE_UNAVAILABLE, "1"], devices=2)
    add_integration(hass, "dlna_dmr", [STATE_UNAVAILABLE], devices=1)
    assert len(coordinator.scan().problems) == 2

    ignored = [device_id_of(hass, domain) for domain in ("zha", "dlna_dmr")]
    for device_id in ignored:
        await async_set_rule(
            hass, coordinator.config_entry, KIND_DEVICE, device_id, IGNORE
        )
    assert coordinator.scan().problems == {}


async def test_events_not_repeated_after_reload(hass: HomeAssistant) -> None:
    """A reload or restart does not announce known problems again."""
    events = async_capture_events(hass, EVENT_PROBLEM)
    entry = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    broken = add_integration(hass, "p1", [STATE_UNAVAILABLE])

    first = DeviceDoctorCoordinator(hass, entry)
    await first.async_refresh()
    await first.async_refresh()
    assert len(events) == 1
    await first.async_unload()

    second = DeviceDoctorCoordinator(hass, entry)
    await second.async_load()
    await second.async_refresh()
    assert broken.entry_id in second.data.confirmed
    assert len(events) == 1
    await second.async_unload()


async def test_loads_streaks_from_0_2_storage(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Storage written by 0.1/0.2 (streaks only) still loads."""
    hass_storage[DOMAIN] = {"version": 1, "key": DOMAIN, "data": {"abc": 3}}
    entry = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)

    coordinator = DeviceDoctorCoordinator(hass, entry)
    await coordinator.async_load()
    assert coordinator.streaks == {"abc": 3}
    await coordinator.async_unload()


async def test_skipped_entities_per_exclusion(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """Entities left out by the exclusions are counted per exclusion type."""
    add_integration(hass, "group", ["on", "off"])  # ignored integration type
    tv = add_integration(hass, "dlna_dmr", [STATE_UNAVAILABLE])
    add_integration(hass, "zha", ["1", "2", "3"], devices=3)
    sensor_id = device_id_of(hass, "zha")
    await async_set_rule(
        hass, coordinator.config_entry, KIND_ENTRY, tv.entry_id, IGNORE
    )
    await async_set_rule(hass, coordinator.config_entry, KIND_DEVICE, sensor_id, IGNORE)

    assert coordinator.scan().skipped == {
        "ignored_integrations": 2,
        "ignored_entries": 1,
        "ignored_devices": 1,
    }


async def test_disabled_entities_are_not_counted(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """Disabled entities have no state and never count as unavailable."""
    entry = add_integration(hass, "shelly", ["on"])
    ent_reg = er.async_get(hass)
    for i in range(3):
        ent_reg.async_get_or_create(
            "sensor",
            "shelly",
            f"disabled_{i}",
            config_entry=entry,
            disabled_by=er.RegistryEntryDisabler.USER,
        )
    assert coordinator.scan().problems == {}


async def test_faults_total_counts_and_persists(hass: HomeAssistant) -> None:
    """Each newly confirmed problem adds one; the total survives a reload."""
    entry = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    add_integration(hass, "p1", [STATE_UNAVAILABLE])
    add_integration(hass, "fancoil", [STATE_UNAVAILABLE])

    first = DeviceDoctorCoordinator(hass, entry)
    await first.async_refresh()
    await first.async_refresh()
    await first.async_refresh()  # still broken: not counted again
    assert first.faults_total == 2
    await first.async_unload()

    second = DeviceDoctorCoordinator(hass, entry)
    await second.async_load()
    await second.async_refresh()
    assert second.faults_total == 2
    await second.async_unload()


async def test_issue_keys_and_plain_placeholders(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """Failed and unavailable entries get their own texts; no English in data."""
    failed = add_integration(hass, "broken", [], state=ConfigEntryState.SETUP_RETRY)
    quiet = add_integration(hass, "p1", [STATE_UNAVAILABLE])
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    issue_reg = ir.async_get(hass)
    failed_issue = issue_reg.async_get_issue(DOMAIN, f"entry_{failed.entry_id}")
    quiet_issue = issue_reg.async_get_issue(DOMAIN, f"entry_{quiet.entry_id}")
    assert failed_issue.translation_key == "entry_retrying"
    assert failed_issue.translation_placeholders["reason"] == "—"
    assert quiet_issue.translation_key == "entry_unavailable"
    assert quiet_issue.translation_placeholders["bad"] == "1"
