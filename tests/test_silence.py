"""Tests for the silence check: devices that stop reporting but stay available."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_doctor.const import (
    CAUSE_SILENT,
    CAUSE_UNAVAILABLE,
    CONF_SILENCE_HOURS,
    CONF_SKIP_ENTITY_DOMAINS,
    DEFAULT_OPTIONS,
    DOMAIN,
    IGNORE,
    KIND_DEVICE,
    SKIP_ENTITY_DOMAINS_1_3,
)
from custom_components.device_doctor.coordinator import (
    DeviceDoctorCoordinator,
    _placeholders,
)
from custom_components.device_doctor.rules import async_set_rule

from .test_coordinator import add_integration, entity_id_of

HOUR = timedelta(hours=1)


@pytest.fixture
async def coordinator(hass: HomeAssistant) -> AsyncGenerator[DeviceDoctorCoordinator]:
    """Return a coordinator with default options (25 h limit, mqtt)."""
    entry = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    coordinator = DeviceDoctorCoordinator(hass, entry)
    yield coordinator
    await coordinator.async_unload()


def device_of(hass: HomeAssistant, domain: str, index: int) -> str:
    """Return the device of a test integration's sensor number ``index``."""
    return er.async_get(hass).async_get(entity_id_of(hass, domain, index)).device_id


def report(hass: HomeAssistant, domain: str, *indexes: int) -> None:
    """Write sensors again with the same value, as an MQTT message does."""
    for index in indexes:
        entity_id = entity_id_of(hass, domain, index)
        hass.states.async_set(entity_id, hass.states.get(entity_id).state)


async def pass_hours(
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
    hours: int,
    *,
    keep_alive: tuple[str, tuple[int, ...]] | None = None,
) -> None:
    """Scan every hour; ``keep_alive`` sensors report before each scan."""
    for _ in range(hours):
        freezer.tick(HOUR)
        if keep_alive:
            report(coordinator.hass, keep_alive[0], *keep_alive[1])
        await coordinator.async_refresh()


async def test_silent_mqtt_device_is_flagged(
    hass: HomeAssistant,
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An MQTT device that stops reporting is flagged; a ZHA one is not."""
    add_integration(hass, "mqtt", ["20.1", "20.2"], devices=2)
    add_integration(hass, "zha", ["on", "on"], devices=2)
    await coordinator.async_refresh()

    await pass_hours(coordinator, freezer, 24, keep_alive=("mqtt", (1,)))
    assert not coordinator.data.candidates

    await pass_hours(coordinator, freezer, 3, keep_alive=("mqtt", (1,)))
    dead = device_of(hass, "mqtt", 0)
    assert set(coordinator.data.confirmed) == {dead}
    problem = coordinator.data.confirmed[dead]
    assert problem.cause == CAUSE_SILENT
    assert problem.issue_key == "device_silent"
    # Never heard since Device Doctor started: shown as "at least".
    assert problem.last_heard is None
    assert _placeholders(hass, problem)["since"].startswith("≥ ")
    assert device_of(hass, "mqtt", 1) in coordinator.data.healthy


async def test_one_active_entity_keeps_device_alive(
    hass: HomeAssistant,
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A rain sensor stuck at 0 is fine while another entity reports."""
    add_integration(hass, "mqtt", ["0", "21.5"], devices=1)
    await coordinator.async_refresh()
    await pass_hours(coordinator, freezer, 30, keep_alive=("mqtt", (1,)))
    assert not coordinator.data.candidates
    assert coordinator.last_heard[device_of(hass, "mqtt", 0)] == (
        dt_util.utcnow().isoformat()
    )


async def test_last_heard_survives_restart(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Startup writes don't count as heard; the last real report is kept."""
    doctor = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    doctor.add_to_hass(hass)
    add_integration(hass, "mqtt", ["1", "2"], devices=2)
    device = device_of(hass, "mqtt", 0)

    first = DeviceDoctorCoordinator(hass, doctor)
    await first.async_refresh()
    freezer.tick(HOUR)
    report(hass, "mqtt", 0, 1)
    heard_at = dt_util.utcnow()
    await first.async_refresh()
    assert first.last_heard[device] == heard_at.isoformat()
    await first.async_unload()

    # "Restart": every entity is written again before Device Doctor starts.
    freezer.tick(HOUR)
    report(hass, "mqtt", 0, 1)
    second = DeviceDoctorCoordinator(hass, doctor)
    await second.async_load()
    await second.async_refresh()
    assert second.last_heard[device] == heard_at.isoformat()

    for _ in range(26):  # over 25 h, then confirmed
        freezer.tick(HOUR)
        report(hass, "mqtt", 1)
        await second.async_refresh()
    problem = second.data.confirmed[device]
    assert problem.cause == CAUSE_SILENT
    assert problem.last_heard == heard_at.isoformat()
    assert problem.since == heard_at.isoformat()
    await second.async_unload()


async def test_rules_hold_silent_devices(
    hass: HomeAssistant,
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Allowed-offline and ignored rules work for silence as for unavailable."""
    add_integration(hass, "mqtt", ["1", "2", "3"], devices=3)
    slow, ignored = device_of(hass, "mqtt", 0), device_of(hass, "mqtt", 1)
    entry = coordinator.config_entry
    await async_set_rule(hass, entry, KIND_DEVICE, slow, "3d")
    await async_set_rule(hass, entry, KIND_DEVICE, ignored, IGNORE)
    await coordinator.async_refresh()

    await pass_hours(coordinator, freezer, 48, keep_alive=("mqtt", (2,)))
    assert not coordinator.data.candidates
    assert coordinator.data.allowed == 1

    await pass_hours(coordinator, freezer, 26, keep_alive=("mqtt", (2,)))
    assert set(coordinator.data.confirmed) == {slow}


async def test_whole_hub_silent_is_one_problem(
    hass: HomeAssistant,
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Most of a hub's devices quiet at once: one repair for the integration."""
    mqtt = add_integration(hass, "mqtt", ["1", "2", "3"], devices=3)
    await coordinator.async_refresh()
    await pass_hours(coordinator, freezer, 27)
    assert set(coordinator.data.confirmed) == {mqtt.entry_id}
    problem = coordinator.data.confirmed[mqtt.entry_id]
    assert problem.cause == CAUSE_SILENT
    assert problem.issue_key == "entry_silent"


async def test_unavailable_wins_over_silent(
    hass: HomeAssistant,
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A device that is unavailable is reported as such, not as silent."""
    add_integration(hass, "mqtt", ["1", "2"], devices=2)
    await coordinator.async_refresh()
    hass.states.async_set(entity_id_of(hass, "mqtt", 0), "unavailable")
    await pass_hours(coordinator, freezer, 27, keep_alive=("mqtt", (1,)))
    (problem,) = coordinator.data.confirmed.values()
    assert problem.cause == CAUSE_UNAVAILABLE
    assert problem.issue_key == "device_problem"


async def test_silence_check_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A silence limit of 0 turns the check off."""
    doctor = MockConfigEntry(
        domain=DOMAIN, options={**DEFAULT_OPTIONS, CONF_SILENCE_HOURS: 0}
    )
    doctor.add_to_hass(hass)
    add_integration(hass, "mqtt", ["1", "2"], devices=2)
    coordinator = DeviceDoctorCoordinator(hass, doctor)
    await coordinator.async_refresh()
    await pass_hours(coordinator, freezer, 30)
    assert not coordinator.data.candidates
    assert not coordinator.last_heard
    assert not coordinator.listening_since
    await coordinator.async_unload()


async def test_last_seen_sensor_is_used(
    hass: HomeAssistant,
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A Zigbee2MQTT 'last seen' sensor counts, even if it was written at startup."""
    mqtt = add_integration(hass, "mqtt", ["1"], devices=1)
    device = device_of(hass, "mqtt", 0)
    last_seen = er.async_get(hass).async_get_or_create(
        "sensor",
        "mqtt",
        "device_0_last_seen",
        suggested_object_id="device_0_last_seen",
        config_entry=mqtt,
        device_id=device,
    )
    seen_at = dt_util.utcnow() - 2 * HOUR
    hass.states.async_set(
        last_seen.entity_id, seen_at.isoformat(), {"device_class": "timestamp"}
    )
    await coordinator.async_refresh()
    assert coordinator.last_heard[device] == seen_at.isoformat()

    await pass_hours(coordinator, freezer, 23)
    assert not coordinator.data.candidates
    await pass_hours(coordinator, freezer, 2)
    assert device in coordinator.data.candidates


async def test_migration_extends_untouched_skip_list(hass: HomeAssistant) -> None:
    """1.4 adds tts, stt, ... to an untouched list and leaves a custom one."""
    untouched = MockConfigEntry(
        domain=DOMAIN,
        minor_version=3,
        options={**DEFAULT_OPTIONS, CONF_SKIP_ENTITY_DOMAINS: SKIP_ENTITY_DOMAINS_1_3},
    )
    custom = MockConfigEntry(
        domain=DOMAIN,
        minor_version=3,
        options={**DEFAULT_OPTIONS, CONF_SKIP_ENTITY_DOMAINS: ["button"]},
    )
    for entry in (untouched, custom):
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.minor_version == 4
    assert (
        untouched.options[CONF_SKIP_ENTITY_DOMAINS]
        == (DEFAULT_OPTIONS[CONF_SKIP_ENTITY_DOMAINS])
    )
    assert custom.options[CONF_SKIP_ENTITY_DOMAINS] == ["button"]
