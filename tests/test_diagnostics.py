"""Tests for the diagnostics download."""

from __future__ import annotations

from homeassistant.components.diagnostics import REDACTED
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.device_doctor.const import DEFAULT_OPTIONS, DOMAIN

from .test_coordinator import add_integration, device_id_of

EMAIL = "someone@example.com"
ERROR = "Cannot connect to 192.168.1.20 as someone"
DEVICE = "Alice's bedroom lamp"


async def test_diagnostics_redacts_titles_and_reasons(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Entry titles, device names and errors never end up in the download."""
    broken = add_integration(
        hass,
        "broken",
        [],
        title=EMAIL,
        state=ConfigEntryState.SETUP_RETRY,
        reason=ERROR,
    )
    add_integration(hass, "zha", [STATE_UNAVAILABLE, "1"], devices=2)
    device_id = device_id_of(hass, "zha")
    dr.async_get(hass).async_update_device(device_id, name=DEVICE)

    doctor = MockConfigEntry(domain=DOMAIN, options=dict(DEFAULT_OPTIONS))
    doctor.add_to_hass(hass)
    assert await hass.config_entries.async_setup(doctor.entry_id)
    await hass.async_block_till_done()
    await doctor.runtime_data.async_refresh()  # second scan confirms

    result = await get_diagnostics_for_config_entry(hass, hass_client, doctor)

    assert EMAIL not in str(result)
    assert "192.168.1.20" not in str(result)
    assert DEVICE not in str(result)

    problems = {p["id"]: p for p in result["confirmed"]}
    assert set(problems) == {broken.entry_id, device_id}
    assert problems == {p["id"]: p for p in result["candidates"]}
    for problem in problems.values():
        assert problem["title"] == REDACTED
        assert problem["reason"] in (REDACTED, None)
    assert problems[broken.entry_id]["reason"] == REDACTED
    # What is useful for debugging stays.
    assert problems[broken.entry_id]["kind"] == "entry"
    assert problems[broken.entry_id]["domain"] == "broken"
    assert problems[device_id]["kind"] == "device"
    assert problems[device_id]["domain"] == "zha"
    assert result["options"] == dict(DEFAULT_OPTIONS)
