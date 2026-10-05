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

For broken integrations the repair offers a **Reload** button: reloading often
revives a connection that died silently.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/Stevenpolak/device_doctor` as type **Integration**
3. Install **Device Doctor** and restart Home Assistant
4. *Settings → Devices & services → Add integration →* **Device Doctor**

### Manual

Copy `custom_components/device_doctor` into your `config/custom_components`
folder and restart.

## Options

*Settings → Devices & services → Device Doctor → Configure*

| Option | Default | Meaning |
|---|---|---|
| Scan interval | 10 min | How often to scan |
| Confirmations | 2 | Scans in a row before a repair is raised |
| Unavailable threshold | 50 % | Flag when more than this share of entities is unavailable |
| Ignored integrations | helpers, `group`, `mobile_app`, … | Never flagged |
| Hub integrations | `zha`, `zwave_js`, `mqtt`, `matter`, `deconz`, `hue` | Judged per device instead of as a whole |
| Ignored entity types | `button`, `event`, `scene`, `update`, … | Types that sit at `unknown` until used |
| Count `unknown` | on | Some integrations report `unknown` when they lose connection |

Disabled and ignored integrations are always skipped.

## Entities

| Entity | |
|---|---|
| `sensor.device_doctor_problems` | Number of confirmed problems; the `problems` attribute lists them |
| `binary_sensor.device_doctor_problem_detected` | `on` while any problem is confirmed |

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

## Development

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt ruff
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
