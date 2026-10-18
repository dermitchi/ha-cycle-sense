"""Replay recorded HA history through the detector: python3 tests/replay.py data/h10.json"""
import json, sys, datetime as dt
sys.path.insert(0, "custom_components/cycle_sense")
from engine.detector import Detector, DetectorConfig
CFG = {"sensor.dartbaord_power": DetectorConfig(end_power=8), "sensor.trockner_power": DetectorConfig(end_power=10, end_delay_s=240)}
for ser in json.load(open(sys.argv[1])):
    eid = ser[0]["entity_id"]; det = Detector(CFG.get(eid, DetectorConfig())); print("=====", eid)
    f = lambda t: dt.datetime.fromtimestamp(t).strftime("%a %d.%m %H:%M")
    for x in ser:
        ts = dt.datetime.fromisoformat(x["last_changed"]).timestamp()
        try: p = float(x["state"])
        except ValueError: p = None
        for e in det.update(ts, p):
            c = e.cycle
            if e.type == "finished" or e.type == "aborted":
                print(f"{e.type:8} {f(c.start)} → Ende {f(c.end)[-5:]}, gemeldet {f(e.ts)[-5:]}  {c.duration_s/60:5.0f} min {c.energy_wh/1000:.2f} kWh ({e.reason})")
            elif e.type == "cleared": print(f"   geleert {f(e.ts)} ({e.reason})")
