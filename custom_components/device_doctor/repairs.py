"""Repair fix flow: reload the failing integration."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import OperationNotAllowed
from homeassistant.core import HomeAssistant


class ReloadEntryRepairFlow(RepairsFlow):
    """Offer to reload the config entry behind a problem."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialise the flow."""
        self._data = data

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Start the flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Confirm, then reload."""
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                description_placeholders={
                    key: str(self._data[key])
                    for key in ("title", "detail", "bad", "total", "reason")
                },
            )

        entry_id = str(self._data["entry_id"])
        if self.hass.config_entries.async_get_entry(entry_id) is None:
            return self.async_abort(reason="entry_not_found")
        try:
            reloaded = await self.hass.config_entries.async_reload(entry_id)
        except OperationNotAllowed:
            reloaded = False
        if not reloaded:
            return self.async_abort(reason="reload_failed")
        # Finishing the flow removes the issue; the next scan raises it again
        # if the reload didn't help.
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create the fix flow for an issue."""
    assert data is not None
    return ReloadEntryRepairFlow(data)
