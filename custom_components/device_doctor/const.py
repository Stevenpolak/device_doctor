"""Constants for Device Doctor."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState

DOMAIN = "device_doctor"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_CONFIRMATIONS = "confirmations"
CONF_THRESHOLD = "threshold"
CONF_SKIP_DOMAINS = "skip_domains"
CONF_IGNORED_DEVICES = "ignored_devices"
CONF_IGNORED_ENTRIES = "ignored_entries"
CONF_HUB_DOMAINS = "hub_domains"
CONF_SKIP_ENTITY_DOMAINS = "skip_entity_domains"
CONF_COUNT_UNKNOWN = "count_unknown"

DEFAULT_OPTIONS: dict[str, object] = {
    CONF_SCAN_INTERVAL: 10,  # minutes
    CONF_CONFIRMATIONS: 2,  # consecutive scans before a problem is raised
    CONF_THRESHOLD: 50,  # percent of entities unavailable
    # Helpers derive their state from other entities, so they only echo the
    # real failure elsewhere. Phones sleep.
    CONF_SKIP_DOMAINS: [
        "derivative",
        "filter",
        "group",
        "integration",
        "min_max",
        "mobile_app",
        "statistics",
        "switch_as_x",
        "template",
        "threshold",
        "trend",
        "utility_meter",
    ],
    # Single config entries and devices that are allowed to be offline.
    CONF_IGNORED_ENTRIES: [],
    CONF_IGNORED_DEVICES: [],
    # Integrations with one config entry for many devices: judged per device.
    CONF_HUB_DOMAINS: ["deconz", "hue", "matter", "mqtt", "zha", "zwave_js"],
    # Entity domains that sit at "unknown" until first used.
    CONF_SKIP_ENTITY_DOMAINS: ["button", "event", "image", "notify", "scene", "update"],
    CONF_COUNT_UNKNOWN: True,
}

FAILED_ENTRY_STATES = frozenset(
    {
        ConfigEntryState.SETUP_ERROR,
        ConfigEntryState.SETUP_RETRY,
        ConfigEntryState.MIGRATION_ERROR,
        ConfigEntryState.FAILED_UNLOAD,
    }
)

# Option sections in the config and options forms.
SECTION_SCANNING = "scanning"
SECTION_EXCLUSIONS = "exclusions"
SECTION_ADVANCED = "advanced"
SECTIONS: dict[str, tuple[str, ...]] = {
    SECTION_SCANNING: (CONF_SCAN_INTERVAL, CONF_CONFIRMATIONS, CONF_THRESHOLD),
    SECTION_EXCLUSIONS: (CONF_SKIP_DOMAINS, CONF_IGNORED_ENTRIES, CONF_IGNORED_DEVICES),
    SECTION_ADVANCED: (
        CONF_HUB_DOMAINS,
        CONF_SKIP_ENTITY_DOMAINS,
        CONF_COUNT_UNKNOWN,
    ),
}

SERVICE_RELOAD_PROBLEMS = "reload_problems"

EVENT_PROBLEM = f"{DOMAIN}_problem"
EVENT_RECOVERED = f"{DOMAIN}_recovered"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1
