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
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_doctor.const import DEFAULT_OPTIONS, DOMAIN
from custom_components.device_doctor.coordinator import DeviceDoctorCoordinator


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
    assert coordinator.scan() == {}


async def test_failed_entry_without_entities(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """An entry that failed setup is flagged even with no entities."""
    entry = add_integration(hass, "broken", [], state=ConfigEntryState.SETUP_RETRY)
    problem = coordinator.scan()[entry.entry_id]
    assert problem.detail == "entry setup_retry"
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
    assert coordinator.scan() == {}


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
    problems = list(coordinator.scan().values())
    assert len(problems) == 1
    assert problems[0].kind == "device"
    assert problems[0].title == "zha device 0"


async def test_hub_down_raises_one_problem(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """When the whole hub is down its devices are not listed separately."""
    entry = add_integration(hass, "zha", [STATE_UNAVAILABLE] * 4, devices=2)
    assert list(coordinator.scan()) == [entry.entry_id]


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
