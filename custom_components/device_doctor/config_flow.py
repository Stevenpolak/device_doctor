"""Config and options flow for Device Doctor."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .const import (
    CONF_CONFIRMATIONS,
    CONF_COUNT_UNKNOWN,
    CONF_HUB_DOMAINS,
    CONF_IGNORED_DEVICES,
    CONF_SCAN_INTERVAL,
    CONF_SKIP_DOMAINS,
    CONF_SKIP_ENTITY_DOMAINS,
    CONF_THRESHOLD,
    DEFAULT_OPTIONS,
    DOMAIN,
    SECTION_ADVANCED,
    SECTION_EXCLUSIONS,
    SECTION_SCANNING,
    SECTIONS,
)


class DeviceDoctorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options straight away, so setup and configuration are one step."""
        if user_input is not None:
            return self.async_create_entry(
                title="Device Doctor", data={}, options=flatten(user_input)
            )
        return self.async_show_form(
            step_id="user", data_schema=build_schema(self.hass, DEFAULT_OPTIONS)
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return DeviceDoctorOptionsFlow()


class DeviceDoctorOptionsFlow(OptionsFlow):
    """Change the options later."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options."""
        if user_input is not None:
            return self.async_create_entry(data=flatten(user_input))
        opts = {**DEFAULT_OPTIONS, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=build_schema(self.hass, opts)
        )


def flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    """Merge the submitted sections into flat options over the defaults."""
    options = dict(DEFAULT_OPTIONS)
    for name in SECTIONS:
        options.update(user_input.get(name, {}))
    return options


def build_schema(hass: HomeAssistant, opts: dict[str, Any]) -> vol.Schema:
    """Return the sectioned form, prefilled with ``opts``."""
    installed = {entry.domain for entry in hass.config_entries.async_entries()} - {
        DOMAIN
    }

    scanning = vol.Schema(
        {
            vol.Required(CONF_SCAN_INTERVAL, default=opts[CONF_SCAN_INTERVAL]): _number(
                1, 120, "min"
            ),
            vol.Required(CONF_CONFIRMATIONS, default=opts[CONF_CONFIRMATIONS]): _number(
                1, 10
            ),
            vol.Required(CONF_THRESHOLD, default=opts[CONF_THRESHOLD]): _number(
                1, 100, "%"
            ),
        }
    )
    exclusions = vol.Schema(
        {
            vol.Optional(
                CONF_SKIP_DOMAINS, default=opts[CONF_SKIP_DOMAINS]
            ): _multi_select(installed | set(opts[CONF_SKIP_DOMAINS])),
            vol.Optional(
                CONF_IGNORED_DEVICES, default=opts[CONF_IGNORED_DEVICES]
            ): DeviceSelector(DeviceSelectorConfig(multiple=True)),
        }
    )
    advanced = vol.Schema(
        {
            vol.Optional(
                CONF_HUB_DOMAINS, default=opts[CONF_HUB_DOMAINS]
            ): _multi_select(installed | set(opts[CONF_HUB_DOMAINS])),
            vol.Optional(
                CONF_SKIP_ENTITY_DOMAINS, default=opts[CONF_SKIP_ENTITY_DOMAINS]
            ): _multi_select({platform.value for platform in Platform}),
            vol.Required(
                CONF_COUNT_UNKNOWN, default=opts[CONF_COUNT_UNKNOWN]
            ): BooleanSelector(),
        }
    )
    return vol.Schema(
        {
            vol.Required(SECTION_SCANNING): section(scanning, {"collapsed": False}),
            vol.Required(SECTION_EXCLUSIONS): section(exclusions, {"collapsed": False}),
            vol.Required(SECTION_ADVANCED): section(advanced, {"collapsed": True}),
        }
    )


def _number(minimum: int, maximum: int, unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(
        min=minimum, max=maximum, step=1, mode=NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _multi_select(options: set[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=sorted(options),
            multiple=True,
            custom_value=True,
            sort=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )
