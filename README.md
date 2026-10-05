# Device Doctor

Finds dead devices and silently failing integrations in Home Assistant.

Sometimes an integration stays **loaded** while every one of its entities is
unavailable. Nothing in the UI flags it, and you only notice days later when a
dashboard is empty or an automation didn't run. Device Doctor scans your whole
system on a schedule and raises a **repair** under *Settings → Repairs* when it
finds:

- an integration that failed to set up (`setup_error`, `setup_retry`, …), even
  if it never created an entity;
- an integration where most entities are unavailable while it claims to be
  loaded;
- a single device behind a hub (Zigbee, Z-Wave, MQTT, Matter, …) that has gone
  silent.

A problem has to be seen on several scans in a row before it is raised, so
reboots and short blips don't cause alerts. Repairs disappear by themselves
once things recover.

Clicking a repair gives you a choice:

- **Reload integration** (integrations only): reloading often revives a
  connection that died silently.
- **Ignore this integration / device**: for things that are allowed to be
  offline. Device Doctor stops checking that one integration entry or device;
  undo it under *Configure → Exclusions*.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/Stevenpolak/device_doctor` as type **Integration**
3. Install **Device Doctor** and restart Home Assistant
4. *Settings → Devices & services → Add integration →* **Device Doctor**

### Manual

Copy `custom_components/device_doctor` into your `config/custom_components`
folder and restart.

Requires Home Assistant 2026.3 or newer.

> **Missing icon in HACS?** The icon ships inside the integration (`brand/`),
> which Home Assistant shows since 2026.3. The HACS store still looks up icons
> in a central database that no longer accepts custom integrations, so it shows
> a placeholder. This is a known HACS issue
> ([hacs/integration#5171](https://github.com/hacs/integration/issues/5171))
> and will resolve itself once HACS is updated.

## Options

The options are shown when you add the integration, and can be changed later
under *Settings → Devices & services → Device Doctor → Configure*. The defaults
work for most setups.

| Section | Option | Default | Meaning |
|---|---|---|---|
| Scanning | Scan interval | 10 min | How often to scan |
| | Confirmations | 2 | Scans in a row before a repair is raised |
| | Unavailable threshold | 50 % | Flag when more than this share of entities is unavailable |
| Exclusions | Ignored integrations | helpers, `group`, `mobile_app`, … | Integration types that are never flagged |
| | Ignored integration entries | none | Single entries allowed to be offline, e.g. one ESPHome device |
| | Ignored devices | none | Devices allowed to be offline, such as a TV that is switched off |
| Advanced | Hub integrations | `zha`, `zwave_js`, `mqtt`, `matter`, `deconz`, `hue` | Judged per device instead of as a whole |
| | Ignored entity types | `button`, `event`, `scene`, `update`, … | Types that sit at `unknown` until used |
| | Count `unknown` | on | Some integrations report `unknown` when they lose connection |

Disabled and ignored integrations are always skipped.

## Entities

| Entity | |
|---|---|
| `sensor.device_doctor_problems` | Number of confirmed problems; the `problems` attribute lists them |
| `binary_sensor.device_doctor_problem_detected` | `on` while any problem is confirmed |
| `sensor.device_doctor_faults_found` | Running total of problems confirmed since install (diagnostic) |
| `sensor.device_doctor_skipped_entities` | Entities left out by your exclusions, with a count per exclusion type as attributes (diagnostic) |
| `button.device_doctor_scan_now` | Scan immediately instead of waiting for the next interval (configuration). A manual scan counts towards the confirmations. |

## Actions

### `device_doctor.reload_problems`

Reloads every integration Device Doctor currently reports as not working, the
same as clicking *Reload* on each repair. Devices behind a hub are skipped,
because reloading a whole Zigbee network won't revive one dead sensor.

With *response* enabled it returns which integrations were reloaded:

```yaml
reloaded:
  - P1 meter
failed: []
```

Handy as a dashboard button. To reload one integration from an automation,
use the built-in `homeassistant.reload_config_entry` with the `entry_id` from
the event below.

## Events

- `device_doctor_problem`: a problem was confirmed
- `device_doctor_recovered`: a confirmed problem cleared

Both carry `id`, `kind` (`entry` or `device`), `title`, `domain`, `entry_id`,
`detail`, `bad`, `total` and `reason`.

### Example: push notification

```yaml
automation:
  - alias: "Device Doctor alert"
    triggers:
      - trigger: event
        event_type: device_doctor_problem
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "Device Doctor"
          message: >
            {{ trigger.event.data.title }} ({{ trigger.event.data.domain }}):
            {{ trigger.event.data.bad }}/{{ trigger.event.data.total }} unavailable
```

### Example: reload automatically, once

```yaml
automation:
  - alias: "Device Doctor auto-reload"
    triggers:
      - trigger: event
        event_type: device_doctor_problem
        event_data:
          kind: entry
    actions:
      - action: homeassistant.reload_config_entry
        data:
          entry_id: "{{ trigger.event.data.entry_id }}"
```

The event fires when a problem is first confirmed, not on every scan, so this
reloads once per outage. If the reload doesn't help, the repair stays and you
can look into it.

## Development

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt ruff
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
