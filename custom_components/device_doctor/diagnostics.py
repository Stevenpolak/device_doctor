"""Diagnostics for Device Doctor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import DeviceDoctorConfigEntry

# A problem's title is another integration's entry title or a device name
# (often an email, username or person's name); its reason is that entry's
# last error (can hold hosts, IP addresses or account details).
TO_REDACT = {"title", "reason"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeviceDoctorConfigEntry
) -> dict[str, Any]:
    """Return the options and the last scan."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return async_redact_data(
        {
            "options": coordinator.options,
            "streaks": coordinator.streaks,
            "rules": [
                {"kind": r.kind, "target_id": r.target_id, "seconds": r.seconds}
                for r in coordinator.rules.values()
            ],
            "last_ok": coordinator.last_ok,
            "down_since": coordinator.down_since,
            "returns": coordinator.returns,
            "candidates": [problem.as_dict() for problem in data.candidates.values()],
            "confirmed": [problem.as_dict() for problem in data.confirmed.values()],
        },
        TO_REDACT,
    )
