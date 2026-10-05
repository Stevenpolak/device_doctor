"""Diagnostics for Device Doctor."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import DeviceDoctorConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeviceDoctorConfigEntry
) -> dict[str, Any]:
    """Return the options and the last scan."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "options": coordinator.options,
        "streaks": coordinator.streaks,
        "candidates": [problem.as_dict() for problem in data.candidates.values()],
        "confirmed": [problem.as_dict() for problem in data.confirmed.values()],
    }
