"""Show phase changes of real runs: python3 tests/phase_replay.py history.json"""

import datetime as dt
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "cycle_sense"))
from engine import Detector, DetectorConfig  # noqa: E402
from engine.phases import PhaseTracker  # noqa: E402

KIND = {"sensor.dartbaord_power": "washer", "sensor.trockner_power": "dryer"}
CFG = {
    "sensor.dartbaord_power": DetectorConfig(end_power=8),
    "sensor.trockner_power": DetectorConfig(end_power=10, end_delay_s=240),
}
oracle = "--oracle" in sys.argv  # progress from the real run length (= perfect match)

for ser in json.load(open(sys.argv[1])):
    eid = ser[0]["entity_id"]
    pts = []
    for x in ser:
        try:
            pts.append((dt.datetime.fromisoformat(x["last_changed"]).timestamp(), float(x["state"])))
        except ValueError:
            pass
    # Pass 1: cycle bounds for the oracle progress.
    det = Detector(CFG[eid])
    bounds = []
    for ts, p in pts:
        for e in det.update(ts, p):
            if e.type == "finished":
                bounds.append((e.cycle.start, e.cycle.end))
    det = Detector(CFG[eid])
    tr = PhaseTracker(KIND[eid])
    print("=====", eid)
    last = None
    for ts, p in pts:
        det.update(ts, p)
        prog = None
        if oracle:
            for a, b in bounds:
                if a <= ts <= b:
                    prog = (ts - a) / (b - a)
        ph = tr.update(ts, p, det.phase == "running", det.phase == "finished", prog)
        if ph != last:
            print(f"  {dt.datetime.fromtimestamp(ts):%a %d.%m %H:%M:%S} {p:6.0f} W → {ph}")
            last = ph
