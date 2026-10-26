"""Scan coordinator for Device Doctor."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CAUSE_SILENT,
    CAUSE_UNAVAILABLE,
    CONF_CONFIRMATIONS,
    CONF_COUNT_UNKNOWN,
    CONF_HUB_DOMAINS,
    CONF_SCAN_INTERVAL,
    CONF_SILENCE_DOMAINS,
    CONF_SILENCE_HOURS,
    CONF_SKIP_DOMAINS,
    CONF_SKIP_ENTITY_DOMAINS,
    CONF_THRESHOLD,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_PROBLEM,
    EVENT_RECOVERED,
    FAILED_ENTRY_STATES,
    KIND_DEVICE,
    KIND_ENTRY,
    RETURNS_WINDOW,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .rules import Rule, async_get_rules, async_refresh_rule_titles, integration_name

_LOGGER = logging.getLogger(__name__)

FAILED_STATE_VALUES = frozenset(state.value for state in FAILED_ENTRY_STATES)

type DeviceDoctorConfigEntry = ConfigEntry[DeviceDoctorCoordinator]


@dataclass(slots=True)
class Problem:
    """A config entry or device that looks broken."""

    id: str  # config entry id or device id
    kind: str  # KIND_ENTRY or KIND_DEVICE
    title: str
    domain: str
    entry_id: str  # config entry to reload
    detail: str  # raw entry state (e.g. "setup_retry"), or the device's area
    bad: int = 0
    total: int = 0
    reason: str | None = None
    # When it was last seen working (ISO), if Device Doctor ever saw it working.
    last_ok: str | None = None
    # Start of this outage: last_ok, or when it was first seen broken.
    since: str | None = None
    offline_for: int = 0  # seconds
    returns_7d: int = 0  # times it came back in the past week
    link: str = ""  # device or integration page in the Home Assistant UI
    reported_at: str | None = None  # when its repair was opened (ISO)
    cause: str = CAUSE_UNAVAILABLE  # or CAUSE_SILENT
    # When it last reported (ISO), for silence-checked integrations; None if
    # Device Doctor never heard from it.
    last_heard: str | None = None

    @property
    def issue_id(self) -> str:
        """Return the repair issue id for this problem."""
        return f"{self.kind}_{self.id}"

    @property
    def issue_key(self) -> str:
        """Return the translation key of the repair issue."""
        if self.cause == CAUSE_SILENT:
            return f"{self.kind}_silent"
        if self.kind == KIND_DEVICE:
            return "device_problem"
        if self.detail == ConfigEntryState.SETUP_RETRY.value:
            return "entry_retrying"
        if self.detail in FAILED_STATE_VALUES:
            return "entry_failed"
        return "entry_unavailable"

    def as_dict(self) -> dict[str, Any]:
        """Return a serialisable representation."""
        return asdict(self)


@dataclass(slots=True)
class Findings:
    """What a single pass over the system found."""

    problems: dict[str, Problem]
    # Entities left out by the user's exclusions, per exclusion type.
    skipped: dict[str, int]
    # Integration entries and hub devices that are working right now.
    healthy: set[str] = field(default_factory=set)
    # Every integration entry and device that still exists.
    known: set[str] = field(default_factory=set)


@dataclass(slots=True)
class ScanResult:
    """Outcome of one scan, including rules and confirmation."""

    candidates: dict[str, Problem] = field(default_factory=dict)
    confirmed: dict[str, Problem] = field(default_factory=dict)
    skipped: dict[str, int] | None = None  # None until the first scan
    allowed: int = 0  # offline, but within an allowed-offline rule
    # Everything found broken, including what a rule allows to be offline.
    offline: dict[str, Problem] = field(default_factory=dict)
    # Integration entries and hub devices that are working right now.
    healthy: set[str] = field(default_factory=set)


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
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # Consecutive scans each problem has been seen, keyed by problem id.
        self.streaks: dict[str, int] = {}
        # Confirmed problems from before a reload or restart, so their
        # "problem" events are not fired a second time.
        self._restored: dict[str, Problem] = {}
        # Problems confirmed since install; only ever goes up.
        self.faults_total = 0
        # Per id: when last seen working, when first seen broken (cleared when
        # it works again), and when it came back in the past week. Timestamps
        # are ISO strings, so a restart does not lose them.
        self.last_ok: dict[str, str] = {}
        self.down_since: dict[str, str] = {}
        self.returns: dict[str, list[str]] = {}
        # Silence check, per id: when it last reported, or (never heard from)
        # since when Device Doctor has been listening.
        self.last_heard: dict[str, str] = {}
        self.listening_since: dict[str, str] = {}
        # Per entity: its last_reported when first seen. Home Assistant writes
        # every entity at startup, so only a later write counts as heard.
        self._baseline: dict[str, datetime] = {}
        self._issue_ids: set[str] = set()
        # Options and rule data at setup; a change to these needs a reload.
        self.settings: tuple[Any, ...] = ()

    @property
    def options(self) -> dict[str, Any]:
        """Return the options merged over the defaults."""
        return {**DEFAULT_OPTIONS, **self.config_entry.options}

    @property
    def rules(self) -> dict[tuple[str, str], Rule]:
        """Return the allowed-offline rules."""
        return async_get_rules(self.config_entry)

    async def async_load(self) -> None:
        """Restore state, so a restart does not reset confirmation."""
        if (data := await self._store.async_load()) is None:
            return
        if "streaks" not in data:  # 0.1/0.2 stored the streaks only
            data = {"streaks": data}
        self.streaks = data["streaks"]
        self._restored = {
            pid: Problem(**problem)
            for pid, problem in data.get("confirmed", {}).items()
        }
        self.faults_total = data.get("faults_total", 0)
        self.last_ok = data.get("last_ok", {})
        self.down_since = data.get("down_since", {})
        self.returns = data.get("returns", {})
        self.last_heard = data.get("last_heard", {})
        self.listening_since = data.get("listening_since", {})

    async def async_unload(self) -> None:
        """Persist state and withdraw our repair issues."""
        await self._store.async_save(self._data_to_store())
        for issue_id in self._issue_ids:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._issue_ids.clear()

    @callback
    def _data_to_store(self) -> dict[str, Any]:
        confirmed = self.data.confirmed if self.data else self._restored
        return {
            "streaks": self.streaks,
            "confirmed": {pid: p.as_dict() for pid, p in confirmed.items()},
            "faults_total": self.faults_total,
            "last_ok": self.last_ok,
            "down_since": self.down_since,
            "returns": self.returns,
            "last_heard": self.last_heard,
            "listening_since": self.listening_since,
        }

    async def _async_update_data(self) -> ScanResult:
        """Run one scan."""
        if not self.hass.is_running:
            # During startup integrations are still loading and look broken.
            return self.data or ScanResult(confirmed=dict(self._restored))

        # Keep rule titles current after a device is renamed or moved.
        await async_refresh_rule_titles(self.hass, self.config_entry)

        now = dt_util.utcnow()
        findings = self.scan(now)
        raw = findings.problems
        self._track(findings, now)
        self.streaks = {pid: self.streaks.get(pid, 0) + 1 for pid in raw}

        for pid, problem in raw.items():
            problem.last_ok = self.last_ok.get(pid)
            if problem.cause == CAUSE_SILENT:
                # Down since it went quiet, not since it crossed the limit.
                problem.since = (
                    problem.last_heard
                    or self.listening_since.get(pid)
                    or self.down_since[pid]
                )
            else:
                problem.since = problem.last_ok or self.down_since[pid]
            problem.offline_for = _seconds_since(problem.since, now)
            problem.returns_7d = len(self.returns.get(pid, []))

        rules = self.rules
        candidates = {
            pid: problem
            for pid, problem in raw.items()
            if not _is_allowed(problem, rules)
        }
        needed = int(self.options[CONF_CONFIRMATIONS])
        confirmed = {
            pid: problem
            for pid, problem in candidates.items()
            if self.streaks[pid] >= needed
        }
        self._sync_issues_and_events(confirmed, findings.healthy, now)
        self._restored = {}
        # Runs after this result has become self.data.
        self._store.async_delay_save(self._data_to_store, 10)
        return ScanResult(
            candidates=candidates,
            confirmed=confirmed,
            skipped=findings.skipped,
            allowed=len(raw) - len(candidates),
            offline=raw,
            healthy=findings.healthy,
        )

    @callback
    def _track(self, findings: Findings, now: datetime) -> None:
        """Update last-seen-working times and the comeback history."""
        stamp = now.isoformat()
        for pid in findings.healthy:
            if pid in self.streaks:  # was broken on the previous scan
                self.returns.setdefault(pid, []).append(stamp)
            self.last_ok[pid] = stamp
            self.down_since.pop(pid, None)
        for pid in findings.problems:
            self.down_since.setdefault(pid, stamp)

        # Forget deleted integrations and devices, and comebacks older than a week.
        for store in (
            self.last_ok,
            self.down_since,
            self.returns,
            self.last_heard,
            self.listening_since,
        ):
            for pid in store.keys() - findings.known:
                del store[pid]
        for pid, stamps in list(self.returns.items()):
            recent = [s for s in stamps if _seconds_since(s, now) <= RETURNS_WINDOW]
            if recent:
                self.returns[pid] = recent
            else:
                del self.returns[pid]

    @callback
    def scan(self, now: datetime | None = None) -> Findings:
        """Find every config entry and hub device that currently looks broken."""
        now = now or dt_util.utcnow()
        opts = self.options
        bad_states = {STATE_UNAVAILABLE}
        if opts[CONF_COUNT_UNKNOWN]:
            bad_states.add(STATE_UNKNOWN)
        skip_domains = {*opts[CONF_SKIP_DOMAINS], DOMAIN}
        hub_domains = set(opts[CONF_HUB_DOMAINS])
        skip_entity_domains = set(opts[CONF_SKIP_ENTITY_DOMAINS])
        threshold = float(opts[CONF_THRESHOLD]) / 100
        silence_limit = timedelta(hours=float(opts[CONF_SILENCE_HOURS]))
        silence_domains = set(opts[CONF_SILENCE_DOMAINS]) if silence_limit else set()
        ignored = [rule for rule in self.rules.values() if rule.ignored]
        ignored_entries = {r.target_id for r in ignored if r.kind == KIND_ENTRY}
        ignored_devices = {r.target_id for r in ignored if r.kind == KIND_DEVICE}

        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)

        all_entries = {
            entry.entry_id: entry
            for entry in self.hass.config_entries.async_entries()
            if not entry.disabled_by and entry.source != SOURCE_IGNORE
        }
        entries = {
            entry_id: entry
            for entry_id, entry in all_entries.items()
            if entry.domain not in skip_domains and entry_id not in ignored_entries
        }

        # [bad, total] per config entry and per hub device
        entry_counts: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
        device_counts: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
        device_entry: dict[str, str] = {}
        skipped = dict.fromkeys(
            ("ignored_integrations", "ignored_entries", "ignored_devices"), 0
        )
        # Silence check: newest report per entry and hub device (absent if
        # nothing was heard), and which ones are checked at all.
        newest: dict[str, datetime] = {}
        listened: set[str] = set()

        # Disabled entities have no state, so they are never counted.
        for state in self.hass.states.async_all():
            if state.domain in skip_entity_domains:
                continue
            reg_entry = ent_reg.async_get(state.entity_id)
            if reg_entry is None or reg_entry.config_entry_id not in all_entries:
                continue
            entry = all_entries[reg_entry.config_entry_id]
            if entry.domain in skip_domains:
                if entry.domain != DOMAIN:
                    skipped["ignored_integrations"] += 1
                continue
            if entry.entry_id in ignored_entries:
                skipped["ignored_entries"] += 1
                continue
            if reg_entry.device_id in ignored_devices:
                skipped["ignored_devices"] += 1
                continue
            is_bad = state.state in bad_states
            counts = entry_counts[reg_entry.config_entry_id]
            counts[0] += is_bad
            counts[1] += 1
            per_device = bool(reg_entry.device_id) and entry.domain in hub_domains
            if per_device:
                counts = device_counts[reg_entry.device_id]
                counts[0] += is_bad
                counts[1] += 1
                device_entry[reg_entry.device_id] = reg_entry.config_entry_id
            if entry.domain in silence_domains:
                pids = [entry.entry_id]
                if per_device:
                    pids.append(reg_entry.device_id)
                listened.update(pids)
                if heard := self._heard(state, reg_entry):
                    for pid in pids:
                        if pid not in newest or heard > newest[pid]:
                            newest[pid] = heard

        # Silent: what hasn't reported for longer than the limit, with when it
        # was last heard (None: never heard from).
        silent: dict[str, str | None] = {}
        for pid in listened:
            last = self._last_heard(pid, newest.get(pid), now)
            if now - last > silence_limit:
                silent[pid] = self.last_heard.get(pid)

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
                    detail=entry.state.value,
                    bad=bad,
                    total=total,
                    reason=entry.reason,
                    link=(
                        f"/config/integrations/integration/{entry.domain}"
                        f"#config_entry={entry_id}"
                    ),
                )
                continue
            if entry.domain not in silence_domains:
                continue
            if entry.domain in hub_domains:
                # Most of a hub's devices silent at once: the broker or bridge
                # is down, so one repair instead of one per device.
                devices = [d for d, e in device_entry.items() if e == entry_id]
                quiet = [d for d in devices if d in silent]
                if len(devices) < 2 or 2 * len(quiet) <= len(devices):
                    continue
                heard = [silent[d] for d in quiet if silent[d]]
                last_heard = max(heard, default=None)
            elif entry_id in silent:
                last_heard = silent[entry_id]
            else:
                continue
            problems[entry_id] = Problem(
                id=entry_id,
                kind=KIND_ENTRY,
                title=entry.title or entry.domain,
                domain=entry.domain,
                entry_id=entry_id,
                detail=entry.state.value,
                bad=bad,
                total=total,
                link=(
                    f"/config/integrations/integration/{entry.domain}"
                    f"#config_entry={entry_id}"
                ),
                cause=CAUSE_SILENT,
                last_heard=last_heard,
            )
        healthy = set(entries) - set(problems)

        # 2. Per device for hub integrations, unless the whole hub is down.
        for device_id, (bad, total) in device_counts.items():
            entry_id = device_entry[device_id]
            if entry_id in problems:
                continue  # can't tell how the device is doing
            cause = CAUSE_UNAVAILABLE
            if bad / total <= threshold:
                if device_id not in silent:
                    healthy.add(device_id)
                    continue
                cause = CAUSE_SILENT
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
                detail=area.name if area else "",
                bad=bad,
                total=total,
                link=f"/config/devices/device/{device_id}",
                cause=cause,
                last_heard=self.last_heard.get(device_id),
            )

        return Findings(
            problems=problems,
            skipped=skipped,
            healthy=healthy,
            known=set(all_entries)
            | {
                device.id
                for entry_id in all_entries
                for device in dr.async_entries_for_config_entry(dev_reg, entry_id)
            },
        )

    @callback
    def _heard(self, state: State, reg_entry: er.RegistryEntry) -> datetime | None:
        """Return when an entity last reported, if after Device Doctor started.

        A "last seen" timestamp sensor (Zigbee2MQTT) is used as is, since it
        survives restarts.
        """
        if state.state == STATE_UNAVAILABLE:
            return None
        baseline = self._baseline.setdefault(state.entity_id, state.last_reported)
        heard = state.last_reported if state.last_reported > baseline else None
        if (
            reg_entry.translation_key == "last_seen"
            or state.entity_id.endswith("_last_seen")
        ) and state.attributes.get("device_class") == "timestamp":
            seen = dt_util.parse_datetime(state.state)
            if seen and seen.tzinfo and (heard is None or seen > heard):
                heard = dt_util.as_utc(seen)
        return heard

    @callback
    def _last_heard(self, pid: str, newest: datetime | None, now: datetime) -> datetime:
        """Store and return when something was last heard from.

        Never heard from: since when Device Doctor has been listening, so the
        silence limit still runs out for something that is dead from the start.
        """
        stored = self.last_heard.get(pid)
        stored_at = dt_util.parse_datetime(stored) if stored else None
        if newest is not None and (stored_at is None or newest > stored_at):
            self.last_heard[pid] = newest.isoformat()
            self.listening_since.pop(pid, None)
            return newest
        if stored_at is not None:
            return stored_at
        listening = self.listening_since.setdefault(pid, now.isoformat())
        return dt_util.parse_datetime(listening) or now

    @callback
    def _sync_issues_and_events(
        self, confirmed: dict[str, Problem], healthy: set[str], now: datetime
    ) -> None:
        """Create, update and delete repair issues; fire transition events."""
        previous = self.data.confirmed if self.data else self._restored

        for pid, problem in confirmed.items():
            problem.reported_at = (
                previous[pid].reported_at if pid in previous else None
            ) or now.isoformat()
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                problem.issue_id,
                # Every repair offers "allow offline" and "ignore".
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=problem.issue_key,
                translation_placeholders=_placeholders(self.hass, problem),
                data={
                    **_placeholders(self.hass, problem),
                    "id": problem.id,
                    "kind": problem.kind,
                    "entry_id": problem.entry_id,
                },
            )
            if pid not in previous:
                self.faults_total += 1
                self.hass.bus.async_fire(EVENT_PROBLEM, problem.as_dict())

        # Only things that actually work again count as recovered, not ones
        # that were ignored, allowed offline or deleted meanwhile.
        for pid in (previous.keys() - confirmed.keys()) & healthy:
            recovered = previous[pid]
            if recovered.since:
                recovered.offline_for = _seconds_since(recovered.since, now)
            self.hass.bus.async_fire(EVENT_RECOVERED, recovered.as_dict())

        current_issue_ids = {problem.issue_id for problem in confirmed.values()}
        for issue_id in self._issue_ids - current_issue_ids:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._issue_ids = current_issue_ids


def _is_allowed(problem: Problem, rules: dict[tuple[str, str], Rule]) -> bool:
    """Return True if a rule allows this problem to be offline for now."""
    rule = rules.get((problem.kind, problem.id))
    if rule is None and problem.kind == KIND_DEVICE:
        # A device rule wins; otherwise its integration's rule applies.
        rule = rules.get((KIND_ENTRY, problem.entry_id))
    if rule is None:
        return False
    return rule.ignored or problem.offline_for <= rule.seconds


def _seconds_since(stamp: str, now: datetime) -> int:
    then = dt_util.parse_datetime(stamp)
    return max(0, int((now - then).total_seconds())) if then else 0


def _placeholders(hass: HomeAssistant, problem: Problem) -> dict[str, str]:
    """Plain values for the repair texts; the wording lives in the translations.

    Hassfest only allows simple {name} placeholders (no ICU plural/select), so
    the texts show these as labelled facts that need no grammar.
    """
    since_text = "—"
    if since := dt_util.parse_datetime(problem.since) if problem.since else None:
        since_text = dt_util.as_local(since).strftime("%Y-%m-%d %H:%M")
        known = problem.last_heard if problem.cause == CAUSE_SILENT else problem.last_ok
        if known is None:
            # Never seen working (or heard from), so at least this long.
            since_text = f"≥ {since_text}"
    return {
        "title": problem.title,
        "domain": integration_name(hass, problem.domain),
        "bad": str(problem.bad),
        "total": str(problem.total),
        "reason": problem.reason or "—",
        "since": since_text,
        "returns_7d": str(problem.returns_7d),
        "link": problem.link,
    }
