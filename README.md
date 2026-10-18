# Cycle Sense

Reliable start/finish detection and program recognition for washing machines, dryers and dishwashers in Home Assistant – based only on a smart plug's power sensor.

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

## Programs: learn ("scan") and recognise

Cycle Sense can learn the programs of your appliance and then recognise them while they run – with **remaining time**, **finish time** and **progress**.

**Scan a program**

1. Type the program name into *Program name (learning)*, e.g. `Cotton 40°`.
2. Turn on *Learn mode* – before or while the program runs (the whole cycle is recorded from its start either way).
3. When the cycle finishes it is saved under that name and learn mode switches off. Scan the same program again to make it more precise.

Forgot to switch it on? Enter the name and press *Learn last cycle*. Programs can be renamed or deleted under *Configure → Manage programs*.

**Automatic learning** – cycles that match a known program improve it; similar unknown cycles are grouped into *Program 1, 2, …* automatically (just rename them). Call `cycle_sense.import_history` to learn from the cycles already in your recorder.

**How recognition works** – every minute the running cycle is aligned with each learned program using dynamic time warping on a log power scale (tolerant to heating taking longer, load sensing etc.). The aligned position gives remaining time and progress. The learned program also makes the end detection smarter: if the program pauses at this point (soaking, dishwasher drying) Cycle Sense waits for it instead of reporting *finished*; once the program is at its end, it reports after 2 minutes instead of the normal end delay.

## Entities

| Entity | Description |
| --- | --- |
| Status | `off`, `running`, `finished` |
| Power | current watts, always shown (0 W when off) |
| Running | binary sensor |
| Program | recognised program (shown from 40 % confidence; attributes: confidence, candidates, learned programs) |
| Remaining time / Finish time / Progress | from the recognised program |
| Elapsed | minutes since start of the running cycle |
| Cycle energy | kWh of the running (or last) cycle |
| Last cycle | end time, with duration / energy / program attributes |
| Cycles | total count |
| Learn mode, Program name (learning), Learn last cycle | program scanning |
| Acknowledge finished | button |

## Services

| Service | |
| --- | --- |
| `cycle_sense.learn_last_cycle` | save the last finished cycle as a recording of a program |
| `cycle_sense.rename_program` | rename a program (renaming to an existing name merges them) |
| `cycle_sense.delete_program` | delete a program |
| `cycle_sense.import_history` | learn from cycles in the recorder history (returns a summary) |

## Events

`cycle_sense_started`, `cycle_sense_finished`, `cycle_sense_aborted`, `cycle_sense_cleared`, `cycle_sense_learned`. `cycle_sense_finished` carries `entry_id`, `name`, `reason`, `start`, `end`, `duration_min`, `energy_kwh`, `program`, `confidence`.

```yaml
triggers:
  - trigger: event
    event_type: cycle_sense_finished
    event_data:
      name: Washer
      reason: quiet
actions:
  - action: notify.mobile_app_my_phone
    data:
      message: >-
        {{ trigger.event.data.program or 'Washer' }} finished after
        {{ trigger.event.data.duration_min | round }} min
```

## Spoken announcements

Add **Cycle Sense → Spoken announcements** once to get an extra device that speaks on your smart speakers (e.g. HomePods via the Apple TV integration) when an appliance finishes. Choose speakers, TTS voice, a sound played right before the voice (via Chime TTS), quiet hours and (optionally) people who must be home. On the device you get: *Announcements* on/off, *Text when finished*, *Text when started* (empty = off), *Volume* (restored afterwards), *Test announcement* and *Last announcement*.

Texts support placeholders: `{geraet}` (appliance), `{programm}` (recognised program), `{dauer}` (minutes), `{energie}` (kWh), `{uhrzeit}` (time). Example: `{geraet} ist fertig – {programm}, {dauer} Minuten.`

## Kurzanleitung (Deutsch)

**Programm einscannen:** Namen ins Feld *Programmname (Einlernen)* schreiben → *Einlernmodus* einschalten (vor oder während des Laufs) → nach dem Ende ist das Programm gespeichert. Vergessen? Namen eintragen und *Letzten Lauf einlernen* drücken. Je öfter ein Programm eingescannt wird, desto genauer werden *Restzeit* und *Fertig um*.

## Development

`pytest tests` runs the engine tests. `python3 tests/replay.py history.json` replays a Home Assistant history export through the detector.
