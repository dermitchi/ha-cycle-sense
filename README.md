# Cycle Sense

Reliable start/finish detection for washing machines, dryers and dishwashers in Home Assistant – based only on a smart plug's power sensor.

Simple "power below X watts" automations misfire: washers drop to standby mid-wash, keep twitching for half an hour after spinning, and dryers pulse during anti-crease. Cycle Sense uses a small state machine instead:

- a cycle **starts** only when power stays above the start threshold for 2 minutes,
- short bursts (anti-crease, post-run twitches) are **ignored** – they neither keep a cycle alive nor start a new one,
- a cycle is **finished** after a configurable stretch without significant activity; the reported end time is when activity actually stopped,
- switching the appliance off (≈0 W), opening the door (optional sensor) or pressing *Acknowledge* clears the finished state,
- the running cycle survives Home Assistant restarts.

Defaults per appliance type were derived from real washer and dryer recordings.

## Installation (HACS)

1. HACS → ⋮ → *Custom repositories* → `https://github.com/ttvmitchi/ha-cycle-sense`, category *Integration*.
2. Install **Cycle Sense**, restart Home Assistant.
3. *Settings → Devices & services → Add integration → Cycle Sense*, pick the plug's power sensor and the appliance type.

## Entities

| Entity | Description |
| --- | --- |
| Status | `off`, `running`, `finished` |
| Running | binary sensor |
| Elapsed | minutes since start of the running cycle |
| Cycle energy | kWh of the running (or last) cycle |
| Last cycle | end time, with duration / energy attributes |
| Cycles | total count |
| Acknowledge finished | button |

## Events

`cycle_sense_started`, `cycle_sense_finished`, `cycle_sense_aborted`, `cycle_sense_cleared` with `entry_id`, `name`, `reason`, `start`, `end`, `duration_min`, `energy_kwh`.

```yaml
triggers:
  - trigger: event
    event_type: cycle_sense_finished
    event_data:
      name: Waschmaschine
actions:
  - action: notify.mobile_app_my_phone
    data:
      message: "Washer finished after {{ trigger.event.data.duration_min | round }} min"
```

## Roadmap

- **v0.2 – program learning:** record ("scan") programs, recognise them live, remaining time / finish time / progress, smarter end detection using the learned program.

## Development

`pytest tests` runs the detector tests. `python3 tests/replay.py history.json` replays a Home Assistant history export through the detector.
