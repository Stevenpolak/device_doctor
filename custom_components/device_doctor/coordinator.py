"""Scan coordinator for Device Doctor."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

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
    EVENT_PROBLEM,
    EVENT_RECOVERED,
    FAILED_ENTRY_STATES,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

KIND_ENTRY = "entry"
KIND_DEVICE = "device"

type DeviceDoctorConfigEntry = ConfigEntry[DeviceDoctorCoordinator]


@dataclass(slots=True)
class Problem:
    """A config entry or device that looks broken."""

    id: str  # config entry id or device id
    kind: str  # KIND_ENTRY or KIND_DEVICE
    title: str
    domain: str
    entry_id: str  # config entry to reload
    detail: str  # entry state, or the device's area
    bad: int = 0
    total: int = 0
    reason: str | None = None

    @property
    def issue_id(self) -> str:
        """Return the repair issue id for this problem."""
        return f"{self.kind}_{self.id}"

    def as_dict(self) -> dict[str, Any]:
        """Return a serialisable representation."""
        return asdict(self)


@dataclass(slots=True)
class ScanResult:
    """Outcome of one scan."""

    candidates: dict[str, Problem] = field(default_factory=dict)
    confirmed: dict[str, Problem] = field(default_factory=dict)


class DeviceDoctorCoordinator(DataUpdateCoordinator[ScanResult]):
    """Periodically scans all integrations and devices."""

    config_entry: DeviceDoctorConfigEntry

    def __init__(self, hass: HomeAssistant, entry: DeviceDoctorConfigEntry) -> None:
        """Initialise the coordinator."""
        options = {**DEFAULT_OPTIONS, **entry.options}
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=int(options[CONF_SCAN_INTERVAL])),
        )
        self._store: Store[dict[str, int]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # Consecutive scans each problem has been seen, keyed by problem id.
        self.streaks: dict[str, int] = {}
        self._issue_ids: set[str] = set()

    @property
    def options(self) -> dict[str, Any]:
        """Return the options merged over the defaults."""
        return {**DEFAULT_OPTIONS, **self.config_entry.options}

    async def async_load(self) -> None:
        """Restore streaks, so a restart does not reset confirmation."""
        if (data := await self._store.async_load()) is not None:
            self.streaks = data

    async def async_unload(self) -> None:
        """Persist streaks and withdraw our repair issues."""
        await self._store.async_save(self.streaks)
        for issue_id in self._issue_ids:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._issue_ids.clear()

    async def _async_update_data(self) -> ScanResult:
        """Run one scan."""
        if not self.hass.is_running:
            # During startup integrations are still loading and look broken.
            return self.data or ScanResult()

        candidates = self.scan()
        self.streaks = {pid: self.streaks.get(pid, 0) + 1 for pid in candidates}
        self._store.async_delay_save(lambda: self.streaks, 10)

        needed = int(self.options[CONF_CONFIRMATIONS])
        confirmed = {
            pid: problem
            for pid, problem in candidates.items()
            if self.streaks[pid] >= needed
        }
        self._sync_issues_and_events(confirmed)
        return ScanResult(candidates=candidates, confirmed=confirmed)

    @callback
    def scan(self) -> dict[str, Problem]:
        """Return every config entry and hub device that currently looks broken."""
        opts = self.options
        bad_states = {STATE_UNAVAILABLE}
        if opts[CONF_COUNT_UNKNOWN]:
            bad_states.add(STATE_UNKNOWN)
        skip_domains = {*opts[CONF_SKIP_DOMAINS], DOMAIN}
        hub_domains = set(opts[CONF_HUB_DOMAINS])
        skip_entity_domains = set(opts[CONF_SKIP_ENTITY_DOMAINS])
        threshold = float(opts[CONF_THRESHOLD]) / 100

        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)

        entries = {
            entry.entry_id: entry
            for entry in self.hass.config_entries.async_entries()
            if not entry.disabled_by
            and entry.source != SOURCE_IGNORE
            and entry.domain not in skip_domains
        }

        # [bad, total] per config entry and per hub device
        entry_counts: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
        device_counts: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
        device_entry: dict[str, str] = {}

        for state in self.hass.states.async_all():
            if state.domain in skip_entity_domains:
                continue
            reg_entry = ent_reg.async_get(state.entity_id)
            if reg_entry is None or reg_entry.config_entry_id not in entries:
                continue
            is_bad = state.state in bad_states
            counts = entry_counts[reg_entry.config_entry_id]
            counts[0] += is_bad
            counts[1] += 1
            if (
                reg_entry.device_id
                and entries[reg_entry.config_entry_id].domain in hub_domains
            ):
                counts = device_counts[reg_entry.device_id]
                counts[0] += is_bad
                counts[1] += 1
                device_entry[reg_entry.device_id] = reg_entry.config_entry_id

        problems: dict[str, Problem] = {}

        # 1. Per config entry: failed setup, or most entities unavailable.
        #    A failed entry may have no entities at all, so check its state too.
        for entry_id, entry in entries.items():
            bad, total = entry_counts.get(entry_id, (0, 0))
            if entry.state in FAILED_ENTRY_STATES or (
                total and bad / total > threshold
            ):
                problems[entry_id] = Problem(
                    id=entry_id,
                    kind=KIND_ENTRY,
                    title=entry.title or entry.domain,
                    domain=entry.domain,
                    entry_id=entry_id,
                    detail=f"entry {entry.state.value}",
                    bad=bad,
                    total=total,
                    reason=entry.reason,
                )

        # 2. Per device for hub integrations, unless the whole hub is down.
        for device_id, (bad, total) in device_counts.items():
            entry_id = device_entry[device_id]
            if entry_id in problems or bad / total <= threshold:
                continue
            device = dev_reg.async_get(device_id)
            if device is None or device.disabled_by:
                continue
            area = area_reg.async_get_area(device.area_id) if device.area_id else None
            problems[device_id] = Problem(
                id=device_id,
                kind=KIND_DEVICE,
                title=device.name_by_user or device.name or device_id,
                domain=entries[entry_id].domain,
                entry_id=entry_id,
                detail=area.name if area else "no area",
                bad=bad,
                total=total,
            )

        return problems

    @callback
    def _sync_issues_and_events(self, confirmed: dict[str, Problem]) -> None:
        """Create, update and delete repair issues; fire transition events."""
        previous = self.data.confirmed if self.data else {}

        for pid, problem in confirmed.items():
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                problem.issue_id,
                # Reloading a whole hub won't revive one dead Zigbee sensor.
                is_fixable=problem.kind == KIND_ENTRY,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=f"{problem.kind}_problem",
                translation_placeholders={
                    "title": problem.title,
                    "domain": problem.domain,
                    "detail": problem.detail,
                    "bad": str(problem.bad),
                    "total": str(problem.total),
                    "reason": problem.reason or "-",
                },
                data={
                    "entry_id": problem.entry_id,
                    "title": problem.title,
                    "detail": problem.detail,
                    "bad": problem.bad,
                    "total": problem.total,
                    "reason": problem.reason or "-",
                },
            )
            if pid not in previous:
                self.hass.bus.async_fire(EVENT_PROBLEM, problem.as_dict())

        for pid in previous.keys() - confirmed.keys():
            self.hass.bus.async_fire(EVENT_RECOVERED, previous[pid].as_dict())

        current_issue_ids = {problem.issue_id for problem in confirmed.values()}
        for issue_id in self._issue_ids - current_issue_ids:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._issue_ids = current_issue_ids
