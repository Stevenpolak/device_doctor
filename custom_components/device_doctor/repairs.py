"""Repair fix flow: reload, allow offline for a while, or ignore."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    OperationNotAllowed,
)
from homeassistant.core import HomeAssistant
import voluptuous as vol

from .const import (
    ALWAYS,
    DOMAIN,
    KIND_ENTRY,
    RETURNS_HINT,
    RULE_ALLOWED_OFFLINE,
)
from .rules import async_set_rule
from .selectors import allowed_offline_selector

PLACEHOLDERS = (
    "title",
    "domain",
    "state",
    "bad",
    "total",
    "has_reason",
    "reason",
    "offline_value",
    "offline_unit",
    "returns_7d",
    "link",
)


class DeviceDoctorRepairFlow(RepairsFlow):
    """Offer to reload, allow offline for a while, or ignore."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialise the flow."""
        self._data = data

    @property
    def _placeholders(self) -> dict[str, str]:
        return {key: str(self._data.get(key, "")) for key in PLACEHOLDERS}

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Let the user pick what to do."""
        menu_options = ["allow_offline", "ignore"]
        if self._data["kind"] == KIND_ENTRY:
            # Reloading a whole hub won't revive one dead Zigbee sensor, so
            # only integrations offer it.
            if int(self._data.get("returns_7d", 0)) >= RETURNS_HINT:
                # It keeps coming back: probably switched off on purpose.
                menu_options = ["allow_offline", "reload", "ignore"]
            else:
                menu_options = ["reload", "allow_offline", "ignore"]
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

    async def async_step_allow_offline(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Ask how long it may be offline, then save a rule."""
        if user_input is not None:
            return self._save_rule(user_input[RULE_ALLOWED_OFFLINE])
        return self.async_show_form(
            step_id="allow_offline",
            data_schema=vol.Schema(
                {
                    vol.Required(RULE_ALLOWED_OFFLINE, default="1d"): (
                        allowed_offline_selector(include_always=False)
                    )
                }
            ),
            description_placeholders=self._placeholders,
        )

    async def async_step_ignore(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Save an "always allowed offline" rule, i.e. stop checking it."""
        return self._save_rule(ALWAYS)

    def _save_rule(self, allowed: str) -> data_entry_flow.FlowResult:
        if (doctor := _loaded_doctor(self.hass)) is None:
            return self.async_abort(reason="not_loaded")
        # Saving the rule reloads Device Doctor, which then applies it.
        async_set_rule(
            self.hass,
            doctor,
            str(self._data["kind"]),
            str(self._data["id"]),
            allowed,
        )
        return self.async_create_entry(data={})


def _loaded_doctor(hass: HomeAssistant) -> ConfigEntry | None:
    return next(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ),
        None,
    )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create the fix flow for an issue."""
    assert data is not None
    return DeviceDoctorRepairFlow(data)
