"""Replay washer runs against learned profiles + a run trimmed to its program end.

    python3 tests/sim_program_end.py history.json diagnostics.json
"""
import datetime as dt, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "cycle_sense"))
from engine import Detector, DetectorConfig, Matcher, ProfileStore, Sample, CycleRecord

hist, diag = sys.argv[1], sys.argv[2]
d = json.load(open(diag))["data"]
store = ProfileStore.from_dict(d["profiles"])
store.unassigned = []
lc = CycleRecord.from_dict(d["detector"]["last_cycle"])
tr = lc.trace()[:61]
store.add_sample("Pflegeleicht 60°", Sample(tr, 61*60, sum(tr)/60, recorded=lc.start, source="learn"))
cfg = DetectorConfig(end_power=8)
m = Matcher(store, 60, 8)
det = Detector(cfg)
def sync():
    if det.cycle is None or det.phase != "running": return
    if getattr(m, "_s", None) != det.cycle.start: m.reset(); m._s = det.cycle.start
    while m.n < len(det.cycle.bins): m.push(det.cycle.bins[m.n])
det.end_delay_fn = lambda q, n: (sync(), m.end_delay(300, 120, 2700))[1]
det.program_end_fn = lambda n: (sync(), m.program_end_reached())[1]
f = lambda t: dt.datetime.fromtimestamp(t).strftime("%a %d.%m %H:%M")
ser = [s for s in json.load(open(hist)) if s[0]["entity_id"] == "sensor.dartbaord_power"][0]
for x in ser:
    ts = dt.datetime.fromisoformat(x["last_changed"]).timestamp()
    try: p = float(x["state"])
    except ValueError: p = None
    for e in det.update(ts, p):
        if e.type == "started": pass
        elif e.type in ("finished", "cleared", "aborted"):
            c = e.cycle; b = m.best() if e.type == "finished" else None
            print(e.type, e.reason, f(c.start), f"{c.duration_s/60:.0f} min", "Meldung", f(e.ts)[-5:], (b.profile.name, round(b.confidence,2)) if b else "")
    sync()
