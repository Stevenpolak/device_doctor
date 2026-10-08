"""Tests for allowed-offline rules, offline tracking and the 0.4 migration."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar, device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.device_doctor.const import (
    ALWAYS,
    CONF_IGNORED_DEVICES,
    CONF_IGNORED_ENTRIES,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_PROBLEM,
    EVENT_RECOVERED,
    KIND_DEVICE,
    KIND_ENTRY,
    SUBENTRY_ALLOWED_OFFLINE,
)
from custom_components.device_doctor.coordinator import DeviceDoctorCoordinator
from custom_components.device_doctor.repairs import async_create_fix_flow
from custom_components.device_doctor.rules import async_get_rules, async_set_rule

from .test_coordinator import add_integration, device_id_of, entity_id_of

HOUR = timedelta(hours=1)


@pytest.fixture
async def coordinator(hass: HomeAssistant) -> AsyncGenerator[DeviceDoctorCoordinator]:
    """Return a coordinator with default options and no rules."""
    entry = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    coordinator = DeviceDoctorCoordinator(hass, entry)
    yield coordinator
    await coordinator.async_unload()


def set_state(hass: HomeAssistant, entry: MockConfigEntry, state: str) -> None:
    """Set every entity of a test integration to one state."""
    for entity_id in hass.states.async_entity_ids():
        if entity_id.startswith(f"sensor.{entry.domain}_"):
            hass.states.async_set(entity_id, state)


async def test_last_ok_tracked_and_persisted(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Healthy scans record 'last seen working'; it survives a reload."""
    doctor = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    doctor.add_to_hass(hass)
    p1 = add_integration(hass, "p1", ["42"])

    first = DeviceDoctorCoordinator(hass, doctor)
    await first.async_refresh()
    seen = first.last_ok[p1.entry_id]
    await first.async_unload()

    freezer.tick(3 * HOUR)
    set_state(hass, p1, STATE_UNAVAILABLE)
    second = DeviceDoctorCoordinator(hass, doctor)
    await second.async_load()
    await second.async_refresh()
    await second.async_refresh()
    problem = second.data.confirmed[p1.entry_id]
    assert problem.last_ok == seen
    assert problem.offline_for == 3 * 3600
    assert (
        problem.link
        == f"/config/integrations/integration/p1#config_entry={p1.entry_id}"
    )
    await second.async_unload()


async def test_returns_counted_and_pruned(
    hass: HomeAssistant,
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Each comeback is counted; comebacks older than a week drop off."""
    inverter = add_integration(hass, "growatt", ["1"])
    for _ in range(3):  # three nights
        set_state(hass, inverter, STATE_UNAVAILABLE)
        await coordinator.async_refresh()
        freezer.tick(8 * HOUR)
        set_state(hass, inverter, "1")
        await coordinator.async_refresh()
        freezer.tick(16 * HOUR)
    assert len(coordinator.returns[inverter.entry_id]) == 3

    set_state(hass, inverter, STATE_UNAVAILABLE)
    await coordinator.async_refresh()
    assert coordinator.data.candidates[inverter.entry_id].returns_7d == 3

    freezer.tick(timedelta(days=8))
    set_state(hass, inverter, "1")
    await coordinator.async_refresh()  # one fresh comeback, three expired
    assert len(coordinator.returns[inverter.entry_id]) == 1


async def test_rule_holds_problem_until_time_is_up(
    hass: HomeAssistant,
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Within the allowed time nothing is raised; after it, a repair is."""
    tv = add_integration(hass, "androidtv_remote", ["on"])
    await coordinator.async_refresh()  # seen working
    await async_set_rule(hass, coordinator.config_entry, KIND_ENTRY, tv.entry_id, "1d")

    set_state(hass, tv, STATE_UNAVAILABLE)
    for _ in range(3):
        freezer.tick(6 * HOUR)
        await coordinator.async_refresh()
    assert tv.entry_id not in coordinator.data.candidates
    assert coordinator.data.allowed == 1

    freezer.tick(7 * HOUR)  # 25 hours offline
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert tv.entry_id in coordinator.data.confirmed


async def test_device_rule_beats_entry_rule(
    hass: HomeAssistant,
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A device's own rule applies before its hub's rule."""
    zha = add_integration(hass, "zha", ["1", "1", "1", "1"], devices=2)
    device_id = device_id_of(hass, "zha")
    await coordinator.async_refresh()
    await async_set_rule(
        hass, coordinator.config_entry, KIND_ENTRY, zha.entry_id, "30d"
    )
    await async_set_rule(hass, coordinator.config_entry, KIND_DEVICE, device_id, "1d")

    for index in (0, 2):  # the sensors of device_0
        hass.states.async_set(entity_id_of(hass, "zha", index), STATE_UNAVAILABLE)
    freezer.tick(timedelta(days=2))
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert device_id in coordinator.data.confirmed


async def test_events_carry_offline_time(
    hass: HomeAssistant,
    coordinator: DeviceDoctorCoordinator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Events include offline_for and last_ok; recovery reports the outage."""
    problems = async_capture_events(hass, EVENT_PROBLEM)
    recovered = async_capture_events(hass, EVENT_RECOVERED)
    p1 = add_integration(hass, "p1", ["42"])
    await coordinator.async_refresh()

    set_state(hass, p1, STATE_UNAVAILABLE)
    freezer.tick(HOUR)
    await coordinator.async_refresh()
    freezer.tick(HOUR)
    await coordinator.async_refresh()
    assert problems[0].data["offline_for"] == 2 * 3600
    assert problems[0].data["last_ok"] is not None

    freezer.tick(HOUR)
    set_state(hass, p1, "42")
    await coordinator.async_refresh()
    assert recovered[0].data["offline_for"] == 3 * 3600


async def test_ignoring_is_not_a_recovery(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """Ignoring a confirmed problem clears it without a 'recovered' event."""
    recovered = async_capture_events(hass, EVENT_RECOVERED)
    p1 = add_integration(hass, "p1", [STATE_UNAVAILABLE])
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await async_set_rule(
        hass, coordinator.config_entry, KIND_ENTRY, p1.entry_id, ALWAYS
    )
    await coordinator.async_refresh()
    assert not coordinator.data.confirmed
    assert recovered == []


async def test_deleted_things_are_forgotten(
    hass: HomeAssistant, coordinator: DeviceDoctorCoordinator
) -> None:
    """Tracking data of removed integrations is dropped."""
    p1 = add_integration(hass, "p1", ["42"])
    await coordinator.async_refresh()
    assert p1.entry_id in coordinator.last_ok

    await hass.config_entries.async_remove(p1.entry_id)
    await coordinator.async_refresh()
    assert p1.entry_id not in coordinator.last_ok


async def test_repair_allow_offline_creates_rule(hass: HomeAssistant) -> None:
    """'Allow offline' on a repair saves a rule, and suggests itself first."""
    doctor = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    doctor.add_to_hass(hass)
    assert await hass.config_entries.async_setup(doctor.entry_id)
    await hass.async_block_till_done()

    data = {
        "id": "tv_entry",
        "kind": KIND_ENTRY,
        "entry_id": "tv_entry",
        "title": "TV",
        "returns_7d": "3",
    }
    flow = await async_create_fix_flow(hass, "issue", data)
    flow.hass, flow.flow_id, flow.handler, flow.context = hass, "t", DOMAIN, {}
    menu = await flow.async_step_init()
    assert menu["menu_options"] == ["allow_offline", "reload", "ignore"]

    form = await flow.async_step_allow_offline()
    assert form["type"] is FlowResultType.FORM
    result = await flow.async_step_allow_offline({"allowed_offline": "3d"})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    rule = async_get_rules(doctor)[KIND_ENTRY, "tv_entry"]
    assert rule.seconds == 3 * 86400


async def test_rule_flow_add_duplicate_and_change(hass: HomeAssistant) -> None:
    """Rules can be added on the Device Doctor page, once, and changed."""
    doctor = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    doctor.add_to_hass(hass)
    assert await hass.config_entries.async_setup(doctor.entry_id)
    await hass.async_block_till_done()
    tv = add_integration(hass, "androidtv_remote", ["on"])
    manager = hass.config_entries.subentries

    async def add() -> dict:
        result = await manager.async_init(
            (doctor.entry_id, SUBENTRY_ALLOWED_OFFLINE), context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.MENU
        result = await manager.async_configure(
            result["flow_id"], {"next_step_id": "entry"}
        )
        return await manager.async_configure(
            result["flow_id"], {"entry": tv.entry_id, "allowed_offline": "1d"}
        )

    result = await add()
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = doctor.subentries.values()
    assert subentry.title == "androidtv_remote (androidtv_remote) · 1 day"

    result = await add()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"

    result = await manager.async_init(
        (doctor.entry_id, SUBENTRY_ALLOWED_OFFLINE),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    result = await manager.async_configure(
        result["flow_id"], {"allowed_offline": ALWAYS}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert async_get_rules(doctor)[KIND_ENTRY, tv.entry_id].always
    assert doctor.subentries[subentry.subentry_id].title.endswith("· Always (ignore)")


async def test_migrates_0_4_ignore_lists(hass: HomeAssistant) -> None:
    """Ignored entries and devices from 0.4 become 'always' rules."""
    doctor = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=1,
        options={
            **DEFAULT_OPTIONS,
            CONF_IGNORED_ENTRIES: ["tv_entry"],
            CONF_IGNORED_DEVICES: ["leak_sensor"],
        },
    )
    doctor.add_to_hass(hass)
    assert await hass.config_entries.async_setup(doctor.entry_id)
    await hass.async_block_till_done()

    assert doctor.minor_version == 2
    assert CONF_IGNORED_ENTRIES not in doctor.options
    rules = async_get_rules(doctor)
    assert rules[KIND_ENTRY, "tv_entry"].always
    assert rules[KIND_DEVICE, "leak_sensor"].always


async def test_device_rule_title_has_area_and_follows_renames(
    hass: HomeAssistant,
) -> None:
    """Rule titles show the area, and follow renames without a reload."""
    doctor = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    doctor.add_to_hass(hass)
    assert await hass.config_entries.async_setup(doctor.entry_id)
    await hass.async_block_till_done()
    add_integration(hass, "zha", ["1"], devices=1)
    device_id = device_id_of(hass, "zha")
    hallway = ar.async_get(hass).async_create("Hallway")
    dev_reg = dr.async_get(hass)
    dev_reg.async_update_device(device_id, area_id=hallway.id)

    await async_set_rule(hass, doctor, KIND_DEVICE, device_id, "7d")
    await hass.async_block_till_done()
    (subentry,) = doctor.subentries.values()
    assert subentry.title == "zha device 0 (Hallway) · 1 week"

    coordinator = doctor.runtime_data
    dev_reg.async_update_device(device_id, name_by_user="Leak sensor")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert doctor.subentries[subentry.subentry_id].title == (
        "Leak sensor (Hallway) · 1 week"
    )
    # A new title alone doesn't reload Device Doctor.
    assert doctor.runtime_data is coordinator
