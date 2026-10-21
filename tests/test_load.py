"""Load estimate from heating energy."""

from engine import ProfileStore, Sample, estimate_load, heat_wh, heating_end
from engine.load import level


def test_heat_counts_only_power_above_motor_level():
    # 10 min at 2300 W heating plus 30 min at 100 W washing.
    trace = [2300.0] * 10 + [100.0] * 30
    assert heat_wh(trace, 60) == 2000 * 10 / 60
    assert heating_end(trace) == 9
    assert heating_end([100.0] * 5) is None


def test_no_calibration_no_estimate():
    assert estimate_load(200, []) is None


def test_single_calibration_full_drum():
    # Real Pflegeleicht 40° runs: full 336 Wh, partial 183 Wh.
    est = estimate_load(183, [(1.0, 336)], 0.3)
    assert est.basis == "single"
    assert 0.3 < est.load < 0.5
    assert estimate_load(336, [(1.0, 336)], 0.3).load == 1.0
    assert estimate_load(500, [(1.0, 336)], 0.3).load == 1.0
    assert estimate_load(10, [(1.0, 336)], 0.3).load == 0.05


def test_line_fit_with_two_loads():
    pts = [(1.0, 336), (0.33, 140)]
    est = estimate_load(140, pts)
    assert est.basis == "line"
    assert abs(est.load - 0.33) < 0.01
    mid = estimate_load(238, pts).load
    assert 0.6 < mid < 0.7


def test_close_loads_fall_back_to_single():
    est = estimate_load(200, [(1.0, 336), (0.9, 320)], 0.3)
    assert est.basis == "single"


def test_levels():
    assert level(0.33) == "low"
    assert level(0.6) == "half"
    assert level(1.0) == "full"


def test_load_label_is_stored_and_found():
    store = ProfileStore()
    sample = Sample(trace=[2000.0] * 5, duration_s=300, energy_wh=160, recorded=1000.0)
    store.add_sample("Pflegeleicht 40°", sample)
    found = store.find_sample(1000.4)
    assert found is sample
    found.load = 0.33
    again = ProfileStore.from_dict(store.to_dict())
    assert again.profiles[0].samples[0].load == 0.33
    # Old stored samples have no load field.
    old = sample.to_dict()
    del old["load"]
    assert Sample.from_dict(old).load is None
