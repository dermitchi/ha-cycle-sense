"""Replay a Home Assistant history export through detector + learning.

    python3 tests/replay.py history.json

The export is the JSON of /api/history/period for one or more power sensors.
Cycles are learned in order (auto-grouping), so later runs show live
recognition: program, confidence and remaining-time error at 50 % elapsed.
"""

import datetime as dt
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "cycle_sense"))
from engine import Detector, DetectorConfig, Matcher, ProfileStore, Sample  # noqa: E402

CFG = {
    "sensor.dartbaord_power": DetectorConfig(end_power=8),
    "sensor.trockner_power": DetectorConfig(end_power=10, end_delay_s=240),
}


def fmt(t):
    return dt.datetime.fromtimestamp(t).strftime("%a %d.%m %H:%M")


for ser in json.load(open(sys.argv[1])):
    eid = ser[0]["entity_id"]
    cfg = CFG.get(eid, DetectorConfig())
    store = ProfileStore()
    matcher = Matcher(store, cfg.bin_s, cfg.end_power)
    det = Detector(cfg)
    probes: dict = {}

    def sync():
        if det.cycle is None or det.phase != "running":
            return
        while matcher.n < len(det.cycle.bins):
            matcher.push(det.cycle.bins[matcher.n])
            m = matcher.best()
            if m:
                probes[matcher.n] = (m.profile.name, m.confidence, m.remaining_s)

    def end_delay(quiet_since, now):
        sync()
        return matcher.end_delay(cfg.end_delay_s, 90, 2700)

    det.end_delay_fn = end_delay
    print("=====", eid)
    for x in ser:
        ts = dt.datetime.fromisoformat(x["last_changed"]).timestamp()
        try:
            p = float(x["state"])
        except ValueError:
            p = None
        for e in det.update(ts, p):
            if e.type == "started":
                matcher.reset()
                probes.clear()
            elif e.type == "finished":
                c = e.cycle
                n = len(c.trace())
                half = probes.get(max(1, n // 2))
                live = ""
                if half:
                    err = (half[2] - (n - n // 2) * 60) / 60
                    live = f"| bei 50%: {half[0]} {half[1]:.0%}, Restzeit-Fehler {err:+.0f} min"
                res = store.learn(Sample(c.trace(), c.duration_s, c.energy_wh), auto_name_fmt="Programm {n}")
                print(f"{fmt(c.start)} {c.duration_s/60:4.0f} min, Meldung +{(e.ts-c.end)/60:.1f} min → {res.profile or '-'} {live}")
        sync()
    print("Programme:", [p.summary() for p in store.profiles], "ungruppiert:", len(store.unassigned))
