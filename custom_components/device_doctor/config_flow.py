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
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
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
    CONF_SCAN_INTERVAL,
    CONF_SKIP_DOMAINS,
    CONF_SKIP_ENTITY_DOMAINS,
    CONF_THRESHOLD,
    DEFAULT_OPTIONS,
    DOMAIN,
)


class DeviceDoctorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup; everything else lives in the options."""
        if user_input is not None:
            return self.async_create_entry(
                title="Device Doctor", data={}, options=dict(DEFAULT_OPTIONS)
            )
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return DeviceDoctorOptionsFlow()


def _number(minimum: int, maximum: int, unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(
        min=minimum, max=maximum, step=1, mode=NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _multi_select(options: list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            multiple=True,
            custom_value=True,
            sort=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class DeviceDoctorOptionsFlow(OptionsFlow):
    """Tune thresholds and exclusions."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        opts = {**DEFAULT_OPTIONS, **self.config_entry.options}
        installed = {
            entry.domain for entry in self.hass.config_entries.async_entries()
        } - {DOMAIN}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=opts[CONF_SCAN_INTERVAL]
                ): _number(1, 120, "min"),
                vol.Required(
                    CONF_CONFIRMATIONS, default=opts[CONF_CONFIRMATIONS]
                ): _number(1, 10),
                vol.Required(CONF_THRESHOLD, default=opts[CONF_THRESHOLD]): _number(
                    1, 100, "%"
                ),
                vol.Required(
                    CONF_SKIP_DOMAINS, default=opts[CONF_SKIP_DOMAINS]
                ): _multi_select(sorted(installed | set(opts[CONF_SKIP_DOMAINS]))),
                vol.Required(
                    CONF_HUB_DOMAINS, default=opts[CONF_HUB_DOMAINS]
                ): _multi_select(sorted(installed | set(opts[CONF_HUB_DOMAINS]))),
                vol.Required(
                    CONF_SKIP_ENTITY_DOMAINS, default=opts[CONF_SKIP_ENTITY_DOMAINS]
                ): _multi_select(sorted(platform.value for platform in Platform)),
                vol.Required(
                    CONF_COUNT_UNKNOWN, default=opts[CONF_COUNT_UNKNOWN]
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
