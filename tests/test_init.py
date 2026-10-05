"""Tests for setup, the config flow and the repair fix flow."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState, ConfigFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_config_flow,
    mock_integration,
    mock_platform,
)
import voluptuous_serialize

from custom_components.device_doctor.config_flow import build_schema
from custom_components.device_doctor.const import (
    CONF_CONFIRMATIONS,
    CONF_IGNORED_DEVICES,
    CONF_THRESHOLD,
    DEFAULT_OPTIONS,
    DOMAIN,
    SECTION_ADVANCED,
    SECTION_EXCLUSIONS,
    SECTION_SCANNING,
)
from custom_components.device_doctor.repairs import async_create_fix_flow


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    """Setting up creates both entities; unloading works."""
    entry = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.device_doctor_problems").state == "0"
    assert (
        hass.states.get("binary_sensor.device_doctor_problem_detected").state == "off"
    )

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


EMPTY_SECTIONS = {SECTION_SCANNING: {}, SECTION_EXCLUSIONS: {}, SECTION_ADVANCED: {}}


async def test_config_and_options_flow(hass: HomeAssistant) -> None:
    """Setup shows the sectioned options; the options flow saves changes."""
    with (
        patch("custom_components.device_doctor.async_setup_entry", return_value=True),
        patch("custom_components.device_doctor.async_unload_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert set(result["data_schema"].schema) == set(EMPTY_SECTIONS)

        # Untouched sections fall back to the defaults.
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], EMPTY_SECTIONS
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        entry = result["result"]
        assert entry.options == DEFAULT_OPTIONS

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                **EMPTY_SECTIONS,
                SECTION_SCANNING: {CONF_THRESHOLD: 75},
                SECTION_EXCLUSIONS: {CONF_IGNORED_DEVICES: ["tv"]},
            },
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_THRESHOLD] == 75
        assert entry.options[CONF_IGNORED_DEVICES] == ["tv"]
        # Options outside the edited sections keep their values.
        assert entry.options[CONF_CONFIRMATIONS] == DEFAULT_OPTIONS[CONF_CONFIRMATIONS]


def _issue_data(entry_id: str) -> dict[str, object]:
    return {
        "entry_id": entry_id,
        "title": "P1 meter",
        "detail": "entry loaded",
        "bad": 32,
        "total": 32,
        "reason": "-",
    }


async def _start_fix_flow(hass: HomeAssistant, entry_id: str):
    flow = await async_create_fix_flow(hass, "entry_x", _issue_data(entry_id))
    flow.hass = hass
    flow.flow_id = "test"
    flow.handler = DOMAIN
    flow.context = {}
    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"]["bad"] == "32"
    return flow


@pytest.fixture
def p1_flow_handler() -> Iterator[None]:
    """Register a config flow handler for the fake 'p1' integration."""
    with mock_config_flow("p1", ConfigFlow):
        yield


def _mock_p1(
    hass: HomeAssistant, setup_result: bool
) -> tuple[MockConfigEntry, AsyncMock]:
    """Register a fake 'p1' integration and add one entry for it."""
    setup_entry = AsyncMock(return_value=setup_result)
    mock_integration(hass, MockModule("p1", async_setup_entry=setup_entry))
    mock_platform(hass, "p1.config_flow", None)
    target = MockConfigEntry(domain="p1", title="P1 meter")
    target.add_to_hass(hass)
    return target, setup_entry


@pytest.mark.usefixtures("p1_flow_handler")
async def test_fix_flow_reloads_entry(hass: HomeAssistant) -> None:
    """Confirming the repair reloads the broken integration."""
    target, setup_entry = _mock_p1(hass, True)

    flow = await _start_fix_flow(hass, target.entry_id)
    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert target.state is ConfigEntryState.LOADED
    setup_entry.assert_awaited_once()


async def test_fix_flow_aborts_for_missing_entry(hass: HomeAssistant) -> None:
    """A repair for an integration that was removed aborts cleanly."""
    flow = await _start_fix_flow(hass, "does_not_exist")
    result = await flow.async_step_confirm({})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"


@pytest.mark.usefixtures("p1_flow_handler")
async def test_fix_flow_aborts_when_reload_fails(hass: HomeAssistant) -> None:
    """If the integration still can't set up, the repair stays open."""
    target, setup_entry = _mock_p1(hass, False)

    flow = await _start_fix_flow(hass, target.entry_id)
    result = await flow.async_step_confirm({})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reload_failed"
    setup_entry.assert_awaited_once()


async def test_form_serializes_for_frontend(hass: HomeAssistant) -> None:
    """The sectioned schema converts to the format the frontend renders."""
    fields = voluptuous_serialize.convert(
        build_schema(hass, DEFAULT_OPTIONS), custom_serializer=cv.custom_serializer
    )
    assert [(f["name"], f["type"]) for f in fields] == [
        (SECTION_SCANNING, "expandable"),
        (SECTION_EXCLUSIONS, "expandable"),
        (SECTION_ADVANCED, "expandable"),
    ]
    assert fields[2]["expanded"] is False
