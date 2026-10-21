"""Program phases from power, modelled on a washer run read along on its panel."""

from engine.phases import (
    COOL,
    DRY,
    END,
    FINAL_SPIN,
    OFF,
    PUMP,
    RINSE,
    WASH,
    PhaseTracker,
)


def feed(tracker, powers, *, start=0.0, step=30.0, running=True, progress=None):
    """Feed 30-s readings; returns the phase after each one."""
    out = []
    for k, p in enumerate(powers):
        prog = progress(k) if callable(progress) else progress
        out.append(tracker.update(start + k * step, p, running, False, prog))
    return out


def teddy_run():
    # Pflegeleicht 40°, small load (real run 21.10.): 8 min heating,
    # 11 min drum, pump, 22 min rinsing with a pump in between, last
    # pump, final spin ramp, quiet.
    return (
        [2000.0] * 16
        + [70.0] * 22
        + [24.0, 8.0]
        + [70.0] * 20
        + [10.0, 4.0, 4.0]
        + [100.0] * 20
        + [24.0, 4.0]
        + [60.0, 130.0, 240.0, 240.0]
        + [14.0, 14.0, 14.0]
    )


def test_washer_phases_with_recognised_program():
    run = teddy_run()
    n = len(run)
    phases = feed(PhaseTracker("washer"), run, progress=lambda k: k / n)
    assert phases[0] == WASH
    assert phases[38] == WASH
    assert phases[39] == PUMP
    assert phases[45] == RINSE
    # The pump between two rinses keeps the panel on rinsing.
    assert phases[63] == RINSE
    assert phases[84] == PUMP
    assert phases[85] == PUMP
    assert FINAL_SPIN in phases[86:89]
    assert phases[-1] == END


def test_washer_without_program_takes_spin_after_long_rinse():
    phases = feed(PhaseTracker("washer"), teddy_run())
    assert phases[39] == PUMP
    assert FINAL_SPIN in phases
    assert phases[-1] == END


def test_intermediate_spin_reverts_to_rinse():
    tracker = PhaseTracker("washer")
    run = [2000.0] * 10 + [70.0] * 12 + [24.0, 8.0] + [70.0] * 24 + [210.0] * 4 + [120.0] * 6
    phases = feed(tracker, run)
    assert FINAL_SPIN in phases
    assert phases[-1] == RINSE


def test_dryer_phases_and_finish():
    tracker = PhaseTracker("dryer")
    # Heating with a short thermostat pause, then drum only.
    phases = feed(tracker, [2400.0] * 10 + [130.0] * 2 + [2400.0] * 10 + [130.0] * 10)
    assert phases[11] == DRY
    assert phases[-1] == COOL
    assert tracker.update(1000.0, 2.0, False, True, None) == END
    assert tracker.update(1100.0, 0.0, False, False, None) == OFF


def test_state_survives_restart():
    tracker = PhaseTracker("washer")
    feed(tracker, [2000.0] * 10 + [70.0] * 14 + [24.0, 8.0] + [70.0] * 4)
    again = PhaseTracker("washer")
    again.restore(tracker.to_dict())
    assert again.phase == RINSE


def test_other_appliances_have_no_phase():
    assert PhaseTracker("dishwasher").phase is None
