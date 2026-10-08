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
    IGNORE,
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
    SUBENTRY_IGNORED,
)
from .rules import (
    async_duration_label,
    async_find_rule,
    async_rule_title,
    async_set_rule,
    async_target_link,
    async_target_title,
    rule_data,
    rule_unique_id,
)
from .selectors import allowed_offline_selector

CONF_DEVICE = "device"
CONF_ENTRY = "entry"


class DeviceDoctorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1
    # 2: ignored entries and devices moved from the options into rules.
    # 3: ignored rules are their own subentry type.
    MINOR_VERSION = 3

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
        return {
            SUBENTRY_IGNORED: IgnoredFlow,
            SUBENTRY_ALLOWED_OFFLINE: AllowedOfflineFlow,
        }


class _RuleFlow(ConfigSubentryFlow):
    """Pick a device on a hub or an integration, then save a rule for it."""

    # Allowed-offline rules also ask for a duration; ignored rules don't.
    with_duration = False

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
            return await self._create(KIND_DEVICE, user_input[CONF_DEVICE], user_input)
        hubs = {**DEFAULT_OPTIONS, **self._get_entry().options}[CONF_HUB_DOMAINS]
        device = DeviceSelector(
            DeviceSelectorConfig(
                filter=[DeviceFilterSelectorConfig(integration=hub) for hub in hubs]
            )
        )
        return self.async_show_form(
            step_id="device", data_schema=self._schema(CONF_DEVICE, device)
        )

    async def async_step_entry(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """A whole integration entry, such as one ESPHome device."""
        if user_input is not None:
            return await self._create(KIND_ENTRY, user_input[CONF_ENTRY], user_input)
        return self.async_show_form(
            step_id="entry",
            data_schema=self._schema(CONF_ENTRY, _entry_select(self.hass)),
        )

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Delete the rule, so the target is checked normally again."""
        subentry = self._get_reconfigure_subentry()
        self.hass.config_entries.async_remove_subentry(
            self._get_entry(), subentry.subentry_id
        )
        return self.async_abort(reason="removed")

    async def _switch(self, allowed: str) -> SubentryFlowResult:
        """Replace the rule by one of the other type (or another duration)."""
        subentry = self._get_reconfigure_subentry()
        await async_set_rule(
            self.hass,
            self._get_entry(),
            subentry.data[RULE_TARGET_KIND],
            subentry.data[RULE_TARGET_ID],
            allowed,
        )
        return self.async_abort(reason="changed")

    async def _target_placeholders(self) -> dict[str, str]:
        """Name, page link and current duration of the rule being changed."""
        subentry = self._get_reconfigure_subentry()
        kind = subentry.data[RULE_TARGET_KIND]
        target_id = subentry.data[RULE_TARGET_ID]
        allowed = subentry.data.get(RULE_ALLOWED_OFFLINE)
        return {
            "title": async_target_title(self.hass, kind, target_id),
            "link": async_target_link(self.hass, kind, target_id),
            "duration": await async_duration_label(self.hass, allowed)
            if allowed
            else "",
        }

    def _schema(self, key: str, target: Any) -> vol.Schema:
        schema: dict[Any, Any] = {vol.Required(key): target}
        if self.with_duration:
            schema[vol.Required(RULE_ALLOWED_OFFLINE, default="1d")] = (
                allowed_offline_selector()
            )
        return vol.Schema(schema)

    async def _create(
        self, kind: str, target_id: str, user_input: dict[str, Any]
    ) -> SubentryFlowResult:
        # One rule per target, whichever type it is.
        if async_find_rule(self._get_entry(), kind, target_id):
            return self.async_abort(reason="already_configured")
        allowed = user_input.get(RULE_ALLOWED_OFFLINE, IGNORE)
        return self.async_create_entry(
            title=await async_rule_title(self.hass, kind, target_id, allowed),
            data=rule_data(kind, target_id, allowed),
            unique_id=rule_unique_id(kind, target_id),
        )


class IgnoredFlow(_RuleFlow):
    """Ignore a device or integration: it is never checked."""

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """The cog: allow it offline for a while instead, or stop ignoring."""
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["allow_offline", "remove"],
            description_placeholders=await self._target_placeholders(),
        )

    async def async_step_allow_offline(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Turn the ignored rule into an allowed-offline rule."""
        if user_input is not None:
            return await self._switch(user_input[RULE_ALLOWED_OFFLINE])
        return self.async_show_form(
            step_id="allow_offline",
            data_schema=vol.Schema(
                {
                    vol.Required(RULE_ALLOWED_OFFLINE, default="1d"): (
                        allowed_offline_selector()
                    )
                }
            ),
            description_placeholders=await self._target_placeholders(),
        )


class AllowedOfflineFlow(_RuleFlow):
    """Allow a device or integration to be offline for a while."""

    with_duration = True

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """The cog: change how long, ignore instead, or stop allowing offline."""
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["duration", "ignore", "remove"],
            description_placeholders=await self._target_placeholders(),
        )

    async def async_step_duration(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change how long the rule allows."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            allowed = user_input[RULE_ALLOWED_OFFLINE]
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=await async_rule_title(
                    self.hass,
                    subentry.data[RULE_TARGET_KIND],
                    subentry.data[RULE_TARGET_ID],
                    allowed,
                ),
                data={**subentry.data, RULE_ALLOWED_OFFLINE: allowed},
            )
        return self.async_show_form(
            step_id="duration",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        RULE_ALLOWED_OFFLINE,
                        default=subentry.data[RULE_ALLOWED_OFFLINE],
                    ): allowed_offline_selector()
                }
            ),
            description_placeholders=await self._target_placeholders(),
        )

    async def async_step_ignore(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Turn the allowed-offline rule into an ignored rule."""
        return await self._switch(IGNORE)


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
