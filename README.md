<p align="center">
  <img src="https://raw.githubusercontent.com/Stevenpolak/device_doctor/main/custom_components/device_doctor/brand/icon@2x.png" width="120" alt="Device Doctor logo" />
</p>

<h1 align="center">Device Doctor</h1>

<p align="center">Finds dead devices and silently failing integrations in Home Assistant.</p>

Device Doctor keeps an eye on your Home Assistant and tells you when an
integration or device quietly stops working: the kind of failure you
normally only notice days later, when a graph has gone flat or an automation
didn't run.

<img width="100%" alt="Two Device Doctor repairs in Home Assistant: an ESPHome integration that is not working and a Zigbee remote that is unavailable" src="https://raw.githubusercontent.com/Stevenpolak/device_doctor/main/docs/repairs.png" />

## Why

Home Assistant shows an integration as *loaded* as long as it started
successfully. If its connection dies afterwards, it often just stays *loaded*
while every sensor behind it turns *unavailable*. Nothing warns you.

Device Doctor checks your whole system every few minutes. When something is
broken, it shows up under **Settings → Repairs**, right next to Home
Assistant's own warnings, and disappears by itself once it works again.

It catches:

- an integration that failed to start, or keeps retrying
- an integration that claims to be running while most of its sensors are unavailable
- a single Zigbee, Z-Wave, Matter or MQTT device that has gone silent, such as a
  leak sensor with a flat battery

To avoid false alarms, something has to look broken on two scans in a row
before you hear about it. A reboot or a short Wi-Fi hiccup won't bother you.

## Installation

Device Doctor needs Home Assistant 2026.3 or newer.

1. In HACS, open the menu (⋮) and choose **Custom repositories**
2. Add `https://github.com/Stevenpolak/device_doctor` with type **Integration**
3. Search for **Device Doctor**, download it, and restart Home Assistant
4. Go to **Settings → Devices & services → Add integration** and pick **Device Doctor**

The setup dialog shows the settings straight away. The defaults suit most
homes, so you can just click **Submit**.

## Usage

**When something breaks**, a repair appears under **Settings → Repairs**.
Click it and choose:

- **Reload integration**: restarts that one integration. This often brings back
  a connection that silently died. (Only offered for integrations; reloading
  your whole Zigbee network won't revive one sensor.)
- **Allow offline for a while**: for things that are switched off now and then,
  like a TV, a soldering iron or solar inverters at night. Pick 1 day, 3 days,
  1 week or 30 days. Device Doctor stays quiet while it's off for less than
  that, and still tells you when it doesn't come back.
- **Ignore**: for things that may be offline for good. Device Doctor stops
  checking that one integration or device.

The repair also tells you how long it has been offline and links to the device
or integration page. If something keeps coming back on its own, the repair
says so and suggests *Allow offline* first.

**Your rules** are listed on the Device Doctor page under **Settings → Devices
& services → Device Doctor**, each marked *Ignored* or *Allowed offline*, for
example *Leak sensor (Hallway)* or *Growatt inverter (growatt_server) · 1 day*.
Each rule's cog lets you change it: how long it may be offline, switch
between *Ignored* and *Allowed offline*, or remove the rule so it's checked
normally again. Use the **+ Ignore** and **+ Allow offline** buttons at the
top to add one without waiting for a repair. The list is sorted alphabetically
by name.

**To change what is checked**, go to **Settings → Devices & services → Device
Doctor → Configure**. The settings are grouped in three sections:

- **Scanning**: how often to scan (10 minutes), how many scans in a row before
  a repair is raised (2), and what share of a device's sensors must be
  unavailable (more than 50 %)
- **Exclusions**: integration types that are never checked, such as helpers
  that only mirror other sensors
- **Advanced**: which integrations are checked per device, which entity types
  are skipped, and whether `unknown` counts as unavailable. You rarely need
  these.

**On the Device Doctor device page** you'll find:

- **Problems**: how many problems there are right now
- **Problem detected**: on while there is at least one problem
- **Faults found**: how many problems were found since you installed it
- **Skipped entities**: how many entities your exclusions leave out
- **Scan now**: scans immediately, handy to check if a fix worked

## Automations

Device Doctor fires an event when a problem is confirmed
(`device_doctor_problem`) and when it clears (`device_doctor_recovered`), so you
can build your own notifications.

**Send a notification to your phone:**

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
            {{ trigger.event.data.title }} stopped working
            ({{ trigger.event.data.bad }} of {{ trigger.event.data.total }} sensors unavailable)
```

**Reload a broken integration automatically, once:**

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

The event fires when a problem is first found, not on every scan, so this
reloads once per outage instead of over and over.

**Only notify when it has been down for more than a day:**

```yaml
automation:
  - alias: "Device Doctor: down for a day"
    triggers:
      - trigger: event
        event_type: device_doctor_problem
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.offline_for > 86400 }}"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          message: "{{ trigger.event.data.title }} has been offline for over a day"
```

**Tell me when it's back:**

```yaml
automation:
  - alias: "Device Doctor: back again"
    triggers:
      - trigger: event
        event_type: device_doctor_recovered
    actions:
      - action: notify.mobile_app_your_phone
        data:
          message: >
            {{ trigger.event.data.title }} is back after
            {{ (trigger.event.data.offline_for / 3600) | round(1) }} hours
```

There's also an action, **`device_doctor.reload_problems`**, that reloads every
integration Device Doctor currently reports as broken. Put it behind a
dashboard button for a one-tap "fix what you can".

<details>
<summary>Event data</summary>

Both events carry:

| Field | Example | Meaning |
|---|---|---|
| `kind` | `entry` / `device` | A whole integration, or one device behind a hub |
| `title` | `P1 meter` | Name of the integration or device |
| `domain` | `homewizard` | Integration type |
| `entry_id` | `e417a3cb…` | Integration entry to reload |
| `detail` | `loaded` / `setup_retry` / `Hallway` | Integration state, or the device's area (empty if it has none) |
| `bad`, `total` | `32`, `32` | Unavailable sensors out of all checked sensors |
| `reason` | `Timeout connecting…` | Last error, if the integration reported one |
| `offline_for` | `7200` | Seconds it has been offline. On `device_doctor_recovered`: how long the outage lasted |
| `last_ok` | `2026-10-08T21:14:03+00:00` | When Device Doctor last saw it working, or `null` if never |
| `since` | `2026-10-08T21:14:03+00:00` | Start of the outage: `last_ok`, or when it was first seen broken |
| `returns_7d` | `3` | How often it came back by itself in the past week |
| `link` | `/config/devices/device/…` | Its page in Home Assistant |

`device_doctor_recovered` only fires when something actually works again, not
when you ignore it or allow it to be offline.

Home Assistant can't see devices while it's switched off itself, so
`offline_for` includes any time Home Assistant was down.

</details>

## Questions

**Why is a device flagged that is simply switched off?**
Device Doctor can't know it's allowed to be off. Click its repair and choose
**Allow offline for a while**, or **Ignore** if it may stay off for good.

**Why isn't my device flagged even though some sensors are unavailable?**
A device is only flagged when more than half of its checked sensors are
unavailable. Disabled sensors, buttons and scenes don't count. You can change
the threshold under **Configure → Scanning**.

**After updating, a repair shows "Translation … MISSING_VALUE" or raw labels like `allow_offline`?**
Your browser still has the texts of the previous version. Reload the page
with Ctrl+Shift+R (Cmd+Shift+R on a Mac), or fully close and reopen the
companion app.

**Which Zigbee integrations are checked?**
All the common ones, device by device:

- **ZHA**, Home Assistant's built-in Zigbee integration
- **Zigbee2MQTT**, through the MQTT integration
- **deCONZ** (ConBee, RaspBee)
- **Philips Hue**, for devices paired to a Hue bridge

The same goes for **Z-Wave JS** and **Matter**. Use another hub, or a Zigbee
setup that's not in this list? Add its integration under **Configure →
Advanced → Hub integrations** and each of its devices is checked on its own.
