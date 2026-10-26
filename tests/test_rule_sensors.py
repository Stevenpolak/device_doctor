"""Tests for the rule and status sensors on the device page of ruled devices."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_doctor.const import (
    DEFAULT_OPTIONS,
    DOMAIN,
    IGNORE,
    KIND_DEVICE,
    KIND_ENTRY,
)
from custom_components.device_doctor.rules import async_find_rule, async_set_rule

from .test_coordinator import add_integration, device_id_of, entity_id_of
from .test_rules import set_state

HOUR = timedelta(hours=1)


async def _setup_doctor(hass: HomeAssistant) -> MockConfigEntry:
    doctor = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    doctor.add_to_hass(hass)
    assert await hass.config_entries.async_setup(doctor.entry_id)
    await hass.async_block_till_done()
    return doctor


async def _add_rule(
    hass: HomeAssistant,
    doctor: MockConfigEntry,
    kind: str,
    target_id: str,
    allowed: str,
) -> str:
    """Save a rule, wait for the reload and return its subentry id."""
    await async_set_rule(hass, doctor, kind, target_id, allowed)
    await hass.async_block_till_done()
    return async_find_rule(doctor, kind, target_id).subentry_id


def _entity(hass: HomeAssistant, subentry_id: str, key: str) -> er.RegistryEntry | None:
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{subentry_id}_{key}")
    return ent_reg.async_get(entity_id) if entity_id else None


async def _scan(hass: HomeAssistant, doctor: MockConfigEntry) -> None:
    await doctor.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_device_rule_sensors_on_target_device(hass: HomeAssistant) -> None:
    """An allowed-offline rule puts both sensors on the device, not on Doctor."""
    doctor = await _setup_doctor(hass)
    zha = add_integration(hass, "zha", ["on"], devices=1)
    device_id = device_id_of(hass, "zha")
    subentry_id = await _add_rule(hass, doctor, KIND_DEVICE, device_id, "3d")

    rule = _entity(hass, subentry_id, "rule")
    status = _entity(hass, subentry_id, "rule_status")
    assert rule.device_id == status.device_id == device_id
    assert rule.config_subentry_id == subentry_id
    assert rule.entity_category == "diagnostic"
    assert hass.states.get(rule.entity_id).state == "3d"
    assert hass.states.get(rule.entity_id).name == "zha device 0 Device Doctor rule"
    # Device Doctor isn't added to the other integration's device.
    device = dr.async_get(hass).async_get(device_id)
    assert device.config_entries == {zha.entry_id}


async def test_ignored_rule_has_no_status(hass: HomeAssistant) -> None:
    """An ignored device only gets the rule sensor."""
    doctor = await _setup_doctor(hass)
    add_integration(hass, "zha", ["on"], devices=1)
    subentry_id = await _add_rule(
        hass, doctor, KIND_DEVICE, device_id_of(hass, "zha"), IGNORE
    )
    assert hass.states.get(_entity(hass, subentry_id, "rule").entity_id).state == (
        "ignored"
    )
    assert _entity(hass, subentry_id, "rule_status") is None


async def test_entry_rule_needs_a_single_device(hass: HomeAssistant) -> None:
    """An integration rule shows on its only device; with more, nowhere."""
    doctor = await _setup_doctor(hass)
    printer = add_integration(hass, "bambu_lab", ["1"], devices=1)
    hub = add_integration(hass, "shelly", ["1", "2"], devices=2)
    single = await _add_rule(hass, doctor, KIND_ENTRY, printer.entry_id, "1d")
    multi = await _add_rule(hass, doctor, KIND_ENTRY, hub.entry_id, "1d")

    assert _entity(hass, single, "rule").device_id == device_id_of(hass, "bambu_lab")
    assert _entity(hass, single, "rule_status") is not None
    assert _entity(hass, multi, "rule") is None
    assert _entity(hass, multi, "rule_status") is None


async def test_deleting_rule_removes_sensors(hass: HomeAssistant) -> None:
    """Deleting the rule deletes its sensors and leaves the device alone."""
    doctor = await _setup_doctor(hass)
    zha = add_integration(hass, "zha", ["on"], devices=1)
    device_id = device_id_of(hass, "zha")
    subentry_id = await _add_rule(hass, doctor, KIND_DEVICE, device_id, "1d")
    assert _entity(hass, subentry_id, "rule") is not None

    hass.config_entries.async_remove_subentry(doctor, subentry_id)
    await hass.async_block_till_done()
    assert _entity(hass, subentry_id, "rule") is None
    assert _entity(hass, subentry_id, "rule_status") is None
    device = dr.async_get(hass).async_get(device_id)
    assert device.config_entries == {zha.entry_id}


async def test_changing_duration_updates_rule_sensor(hass: HomeAssistant) -> None:
    """A new duration for the same rule shows on the same sensor."""
    doctor = await _setup_doctor(hass)
    add_integration(hass, "zha", ["on"], devices=1)
    device_id = device_id_of(hass, "zha")
    subentry_id = await _add_rule(hass, doctor, KIND_DEVICE, device_id, "1d")
    assert await _add_rule(hass, doctor, KIND_DEVICE, device_id, "30d") == subentry_id
    assert hass.states.get(_entity(hass, subentry_id, "rule").entity_id).state == (
        "30d"
    )


async def test_status_follows_offline_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """ok → allowed offline → problem once the time is up → ok on recovery."""
    doctor = await _setup_doctor(hass)
    # Two devices, so the hub itself keeps working while device 0 is offline.
    add_integration(hass, "zha", ["on", "on"], devices=2)
    device_id = device_id_of(hass, "zha")
    sensor = entity_id_of(hass, "zha", 0)
    subentry_id = await _add_rule(hass, doctor, KIND_DEVICE, device_id, "1d")
    entity_id = _entity(hass, subentry_id, "rule_status").entity_id

    state = hass.states.get(entity_id)
    assert state.state == "ok"
    assert state.attributes["last_ok"] is not None
    assert state.attributes["offline_since"] is None
    assert state.attributes["reported_at"] is None

    hass.states.async_set(sensor, STATE_UNAVAILABLE)
    freezer.tick(HOUR)
    await _scan(hass, doctor)
    state = hass.states.get(entity_id)
    assert state.state == "allowed_offline"
    # Not reported yet: when the day runs out.
    offline_since = state.attributes["offline_since"]
    assert offline_since == state.attributes["last_ok"]
    expected = (dt_util.parse_datetime(offline_since) + timedelta(days=1)).isoformat()
    assert state.attributes["reported_at"] == expected

    freezer.tick(24 * HOUR)
    await _scan(hass, doctor)
    await _scan(hass, doctor)  # two scans confirm it
    state = hass.states.get(entity_id)
    assert state.state == "problem"
    assert state.attributes["reported_at"] == dt_util.utcnow().isoformat()

    reported_at = state.attributes["reported_at"]
    freezer.tick(HOUR)
    await _scan(hass, doctor)
    assert hass.states.get(entity_id).attributes["reported_at"] == reported_at

    hass.states.async_set(sensor, "on")
    await _scan(hass, doctor)
    state = hass.states.get(entity_id)
    assert state.state == "ok"
    assert state.attributes["offline_since"] is None


async def test_status_unknown_when_not_checked(hass: HomeAssistant) -> None:
    """A device that can't be judged (its hub is down) has an unknown status."""
    doctor = await _setup_doctor(hass)
    zha = add_integration(hass, "zha", ["on"], devices=1)
    subentry_id = await _add_rule(
        hass, doctor, KIND_DEVICE, device_id_of(hass, "zha"), "1d"
    )
    entity_id = _entity(hass, subentry_id, "rule_status").entity_id
    set_state(hass, zha, STATE_UNAVAILABLE)  # every entity: the hub is down
    await _scan(hass, doctor)
    assert hass.states.get(entity_id).state == STATE_UNKNOWN
