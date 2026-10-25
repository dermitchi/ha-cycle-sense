"""Remaining time and when it is reliable enough to show."""

from engine import Run, estimate_eta

HEAT = 2400.0
DRUM = 130.0


def dryer(minutes: int, cool: int = 5) -> list[float]:
    return [HEAT] * (minutes - cool) + [DRUM] * cool


def test_fixed_length_program_is_reliable_right_away():
    # 20 Min warm: every run lasts ~20 min.
    runs = [Run(d * 60, 6, 300) for d in (20, 20, 20, 21)]
    eta = estimate_eta(2 * 60, dryer(20)[:3], 60, runs)
    assert eta.reliable
    assert 16 * 60 <= eta.remaining_s <= 18 * 60


def test_sensor_drying_waits_for_the_cooling():
    # Schranktrocknen: 18–56 min depending on how wet the laundry is.
    runs = [Run(d * 60, 6, 1000) for d in (56, 18, 37, 18)]
    trace = dryer(40)
    for n in (5, 15, 30):
        assert not estimate_eta(20 * 60, trace[:n], 60, runs).reliable
    # Three bins of cooling: the heating is over, cooling takes 6 min.
    eta = estimate_eta(20 * 60, trace[:38], 60, runs)
    assert eta.reliable
    assert eta.remaining_s == 3 * 60


def test_few_long_runs_left_are_not_trusted():
    # Washer tails 36–50 and 71–72 min: a run past 50 min of tail could be
    # either, the two long runs alone must not decide.
    runs = [Run(d * 60, t, 400) for d, t in ((50, 42), (85, 71), (85, 72), (46, 37), (61, 36))]
    trace = [2000.0] * 10 + [100.0] * 55
    eta = estimate_eta(28 * 60, trace, 60, runs)
    assert not eta.reliable


def test_load_set_too_low_is_dropped_once_outgrown():
    # 25.10.: dryer set to “little” (33 %), but the laundry needed much
    # longer. The load line said ~14 min; after 6 min the run had already
    # used more energy than a whole 33 % run.
    runs = [
        Run(56 * 60, 5, 1896, None),
        Run(18 * 60, 6, 334, 0.33),
        Run(37 * 60, 6, 1171, 0.67),
        Run(18 * 60, 6, 426, 0.5),
    ]
    early = estimate_eta(40 * 60, [HEAT] * 4, 60, runs, 0.33)
    assert early.remaining_s < 15 * 60
    late = estimate_eta(40 * 60, [HEAT] * 8, 60, runs, 0.33)
    assert late.remaining_s == 40 * 60
    assert not late.reliable
