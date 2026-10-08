"""Config and options flow for Device Doctor."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    SOURCE_IGNORE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceFilterSelectorConfig,
    DeviceSelector,
    DeviceSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
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
    KIND_DEVICE,
    KIND_ENTRY,
    RULE_ALLOWED_OFFLINE,
    RULE_TARGET_ID,
    RULE_TARGET_KIND,
    SECTION_ADVANCED,
    SECTION_EXCLUSIONS,
    SECTION_SCANNING,
    SECTIONS,
    SUBENTRY_ALLOWED_OFFLINE,
)
from .rules import async_target_title, rule_unique_id
from .selectors import allowed_offline_selector

CONF_DEVICE = "device"
CONF_ENTRY = "entry"


class DeviceDoctorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1
    # 2: ignored entries and devices moved from the options into rules.
    MINOR_VERSION = 2

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

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Allowed-offline rules are listed and edited on the Device Doctor page."""
        return {SUBENTRY_ALLOWED_OFFLINE: AllowedOfflineFlow}


class AllowedOfflineFlow(ConfigSubentryFlow):
    """Add an allowed-offline rule, or change how long it allows."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick what the rule is for."""
        return self.async_show_menu(
            step_id="user", menu_options=[CONF_DEVICE, CONF_ENTRY]
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """A device behind a hub, such as one Zigbee sensor."""
        if user_input is not None:
            return self._create(
                KIND_DEVICE, user_input[CONF_DEVICE], user_input[RULE_ALLOWED_OFFLINE]
            )
        hubs = {**DEFAULT_OPTIONS, **self._get_entry().options}[CONF_HUB_DOMAINS]
        device = DeviceSelector(
            DeviceSelectorConfig(
                filter=[DeviceFilterSelectorConfig(integration=hub) for hub in hubs]
            )
        )
        return self.async_show_form(
            step_id="device", data_schema=_rule_schema(CONF_DEVICE, device)
        )

    async def async_step_entry(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """A whole integration entry, such as one ESPHome device."""
        if user_input is not None:
            return self._create(
                KIND_ENTRY, user_input[CONF_ENTRY], user_input[RULE_ALLOWED_OFFLINE]
            )
        return self.async_show_form(
            step_id="entry",
            data_schema=_rule_schema(CONF_ENTRY, _entry_select(self.hass)),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change how long the rule allows."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data={
                    **subentry.data,
                    RULE_ALLOWED_OFFLINE: user_input[RULE_ALLOWED_OFFLINE],
                },
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        RULE_ALLOWED_OFFLINE,
                        default=subentry.data[RULE_ALLOWED_OFFLINE],
                    ): allowed_offline_selector()
                }
            ),
            description_placeholders={"title": subentry.title},
        )

    def _create(self, kind: str, target_id: str, allowed: str) -> SubentryFlowResult:
        unique_id = rule_unique_id(kind, target_id)
        if any(
            subentry.unique_id == unique_id
            for subentry in self._get_entry().subentries.values()
        ):
            return self.async_abort(reason="already_configured")
        return self.async_create_entry(
            title=async_target_title(self.hass, kind, target_id),
            data={
                RULE_TARGET_KIND: kind,
                RULE_TARGET_ID: target_id,
                RULE_ALLOWED_OFFLINE: allowed,
            },
            unique_id=unique_id,
        )


def _rule_schema(key: str, target: Any) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(key): target,
            vol.Required(
                RULE_ALLOWED_OFFLINE, default="1d"
            ): allowed_offline_selector(),
        }
    )


def _entry_select(hass: HomeAssistant) -> SelectSelector:
    """Pick one integration entry, labelled 'title (domain)'."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(
                    value=entry.entry_id,
                    label=async_target_title(hass, KIND_ENTRY, entry.entry_id),
                )
                for entry in hass.config_entries.async_entries()
                if entry.domain != DOMAIN and entry.source != SOURCE_IGNORE
            ],
            sort=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


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
