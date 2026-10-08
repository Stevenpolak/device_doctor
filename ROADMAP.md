# Roadmap

Order: first make Device Doctor complete and operational, then get it into
the HACS default store, then translate.

## 1. Features and operation: v0.5.0

Released first as beta `v0.5.0b1` (pre-release; enable *Show beta versions*
for Device Doctor in HACS), then as `v0.5.0`.

**Allowed offline**: for devices that are legitimately off now and then
(soldering iron, a TV remote when the TV is off, solar inverters at night).

- [x] Track "last seen working" per integration and device, kept across
      restarts; forget integrations and devices once they are deleted
- [x] Count how often something came back in the past 7 days
- [x] Rules "allowed offline for 1 day / 3 days / 1 week / 30 days", stored as
      rules on the Device Doctor page (config subentries), editable and
      removable there
- [x] A device rule wins over a rule for its integration
- [x] Repair menu: Reload (integrations only) · Allow offline · Ignore;
      *Allow offline* first when it came back at least twice this week
- [x] Repair text shows how long it has been offline, and a link to the
      device or integration page
- [x] Events `device_doctor_problem` / `device_doctor_recovered` get
      `offline_for` (seconds) and `last_ok`; on recovery `offline_for` is the
      length of the outage
- [x] README: allowed offline, new event fields, examples "notify only after
      a day" and "X is back after …"
- [x] Tests for all of the above, including time travel

**Decided**
- [x] *Ignore* is merged into the rules as duration "Always" (one list);
      ignored entries and devices from 0.4 are migrated automatically

**Verify on a real install**
- [ ] Plural texts render ("1 of 1 entity" / "32 of 32 entities"); if not,
      switch to preformatted text
- [ ] The link in a repair opens inside Home Assistant, in the browser and in
      the companion app
- [ ] An allowed-offline rule on the Growatt inverters behaves overnight

## 2. HACS default store

Today Device Doctor installs as a *custom repository*. In the default store
anyone can find it in HACS without adding the URL.

Requirements (already met are ticked):
- [x] Public GitHub repository with description, topics and issues enabled
- [x] `hacs.json` with a name; `manifest.json` with all required keys
- [x] Brand icon inside the integration (`brand/icon.png`)
- [x] HACS action and Hassfest pass without errors or ignores
- [x] At least one GitHub release, created after the checks passed

Fixes and checks before submitting:
- [ ] Remove `render_readme` from `hacs.json` (no longer a documented key)
- [ ] Consider `hide_default_branch: true`, so users only install releases
- [ ] A stable release (not a beta) as latest release
- [ ] Issue templates: bug report asking for the diagnostics download and
      Home Assistant version; feature request
- [ ] README check: installation via the default store once accepted,
      screenshots up to date
- [ ] Fresh install test: add as custom repository on a clean Home Assistant,
      install, set up, restart, remove
- [ ] Review the code once more against Home Assistant's integration quality
      checklist (runtime data, unload, diagnostics, translations of errors)
- [ ] Submit: fork `hacs/default`, branch from master, add
      `Stevenpolak/device_doctor` to the `integration` file in alphabetical
      order, fill in the PR template, from the personal account

Known and outside our control: the HACS store shows no icon for integrations
that ship their own `brand/` folder
([hacs/integration#5171](https://github.com/hacs/integration/issues/5171)).

## 3. Translations: later

The texts are already prepared for translation (no English in the code,
plural-aware wording, `tests/test_translations.py` guards every language
file). What remains:

- [ ] Dutch first, reviewed by Steven; then de, fr, es, it, pt-BR, pl, sv, da,
      nb, cs
- [ ] Use Home Assistant's own UI translations as glossary for menu names and
      tone
- [ ] README section "Translations": how to correct or add a language
- [ ] Only if many contributors show up: Crowdin or Hosted Weblate
