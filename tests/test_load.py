"""Load estimate from heating energy."""

from engine import (
    ProfileStore,
    Sample,
    blend_remaining,
    estimate_load,
    heat_wh,
    heating_end,
    predict_duration,
    predict_remaining,
    tail_bins,
)
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


def test_remaining_from_program_tail():
    # Template: 13 min heating, then 35 min rinse/spin.
    full = [2000.0] * 13 + [100.0] * 35
    assert tail_bins(full) == 35
    # Small load: heating over after 6 min, 4 quiet bins seen so far.
    small = [2000.0] * 6 + [100.0] * 4
    assert predict_remaining(small, [35], 60) == 31 * 60
    # Still heating (or just stopped): no prediction yet.
    assert predict_remaining([2000.0] * 6 + [100.0], [35], 60) is None
    assert predict_remaining(small, [], 60) is None
    # Median of the program's tails.
    assert predict_remaining(small, [30, 35, 50], 60) == 31 * 60


def test_blend_hands_over_to_shape_match_at_the_end():
    # Early: prediction wins.
    assert blend_remaining(3000, 2400, 600) == 1800
    # At the predicted end the shape match takes over completely.
    assert blend_remaining(300, 2400, 2400) == 300
    mid = blend_remaining(600, 2400, 2100)
    assert 300 < mid < 600


def test_duration_scales_with_load_for_sensor_drying():
    # Real Schranktrocknen: full drum ~56 min, a third ~18 min.
    pts = [(1.0, 56 * 60), (0.33, 18 * 60)]
    half = predict_duration(0.5, pts) / 60
    assert 25 < half < 30
    assert predict_duration(0.05, pts) >= 9 * 60


def test_duration_needs_two_different_loads():
    # A timed program run once (or twice with similar loads) must not be scaled.
    assert predict_duration(1.0, [(0.33, 20 * 60)]) is None
    assert predict_duration(1.0, [(0.33, 20 * 60), (0.4, 20 * 60)]) is None
    assert predict_duration(1.0, [(None, 20 * 60), (0.33, 20 * 60)]) is None
    # Same length at different loads (timed): no positive slope.
    assert predict_duration(1.0, [(0.2, 20 * 60), (1.0, 20 * 60)]) is None
