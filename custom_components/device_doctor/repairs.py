"""Repair fix flow: reload the failing integration, or ignore the problem."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntryState, OperationNotAllowed
from homeassistant.core import HomeAssistant

from .const import CONF_IGNORED_DEVICES, CONF_IGNORED_ENTRIES, DEFAULT_OPTIONS, DOMAIN
from .coordinator import KIND_ENTRY

PLACEHOLDERS = ("title", "domain", "detail", "bad", "total", "reason")


class DeviceDoctorRepairFlow(RepairsFlow):
    """Offer to reload the integration behind a problem, or to ignore it."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialise the flow."""
        self._data = data

    @property
    def _placeholders(self) -> dict[str, str]:
        return {key: str(self._data.get(key, "-")) for key in PLACEHOLDERS}

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Let the user pick what to do."""
        if self._data["kind"] == KIND_ENTRY:
            menu_options = ["reload", "ignore"]
        else:
            # Reloading a whole hub won't revive one dead Zigbee sensor.
            menu_options = ["ignore"]
        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
            description_placeholders=self._placeholders,
        )

    async def async_step_reload(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Reload the config entry."""
        entry_id = str(self._data["entry_id"])
        if self.hass.config_entries.async_get_entry(entry_id) is None:
            return self.async_abort(reason="entry_not_found")
        try:
            reloaded = await self.hass.config_entries.async_reload(entry_id)
        except OperationNotAllowed:
            reloaded = False
        if not reloaded:
            return self.async_abort(
                reason="reload_failed", description_placeholders=self._placeholders
            )
        # Finishing the flow removes the issue; the next scans raise it again
        # if the reload didn't help.
        return self.async_create_entry(data={})

    async def async_step_ignore(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Add the integration entry or device to Device Doctor's exclusions."""
        doctor = next(
            (
                entry
                for entry in self.hass.config_entries.async_entries(DOMAIN)
                if entry.state is ConfigEntryState.LOADED
            ),
            None,
        )
        if doctor is None:
            return self.async_abort(reason="not_loaded")

        key = (
            CONF_IGNORED_ENTRIES
            if self._data["kind"] == KIND_ENTRY
            else CONF_IGNORED_DEVICES
        )
        options = {**DEFAULT_OPTIONS, **doctor.options}
        options[key] = sorted({*options[key], str(self._data["id"])})
        # Changing the options reloads Device Doctor, which rescans without it.
        self.hass.config_entries.async_update_entry(doctor, options=options)
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create the fix flow for an issue."""
    assert data is not None
    return DeviceDoctorRepairFlow(data)
