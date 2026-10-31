"""Detector behaviour on synthetic power traces."""

from engine import Detector, DetectorConfig, EventType, FinishReason, Phase


def run(segments, cfg=None, step=30):
    """segments: list of (seconds, watts). Returns detector and all events."""
    det = Detector(cfg or DetectorConfig())
    events, t = [], 0.0
    for dur, watts in segments:
        end = t + dur
        while t < end:
            events += det.update(t, watts)
            t += step
    events += det.tick(t + 3600)
    return det, events


def types(events):
    return [e.type for e in events]


def test_normal_cycle_finishes_after_end_delay():
    det, ev = run([(600, 2), (3600, 2000), (1200, 2)])
    assert types(ev) == [EventType.STARTED, EventType.FINISHED]
    fin = ev[1]
    assert fin.cycle.end == 4200
    assert fin.ts == 4200 + 300
    assert det.phase == Phase.FINISHED


def test_short_pause_does_not_end_cycle():
    _, ev = run([(1800, 100), (210, 2), (1800, 100), (900, 2)])
    assert types(ev) == [EventType.STARTED, EventType.FINISHED]


def test_spikes_after_end_are_ignored():
    tail = [(30, 30), (150, 2)] * 15
    _, ev = run([(3000, 150), (60, 2)] + tail + [(600, 2)])
    assert types(ev) == [EventType.STARTED, EventType.FINISHED]
    assert ev[1].cycle.end == 3000


def test_anti_crease_pulses_do_not_start_cycle():
    _, ev = run([(60, 2)] + [(60, 130), (150, 2)] * 20)
    assert ev == []


def test_switch_off_clears_finished():
    det, ev = run([(1800, 500), (600, 2), (120, 0)])
    assert types(ev) == [EventType.STARTED, EventType.FINISHED, EventType.CLEARED]
    assert ev[2].reason == FinishReason.SWITCHED_OFF
    assert det.phase == Phase.OFF


def test_too_short_cycle_is_aborted():
    _, ev = run([(180, 500), (900, 2)])
    assert types(ev) == [EventType.STARTED, EventType.ABORTED]


def test_unavailable_does_not_end_cycle():
    _, ev = run([(1200, 500), (900, None), (1200, 500), (900, 2)])
    assert types(ev) == [EventType.STARTED, EventType.FINISHED]
    assert ev[1].cycle.end == 3300


def test_sparse_samples_give_exact_times():
    det = Detector(DetectorConfig())
    ev = det.update(0, 1000) + det.update(3600, 2) + det.update(7200, 2)
    assert types(ev) == [EventType.STARTED, EventType.FINISHED]
    assert ev[0].ts == 120 and ev[1].ts == 3900


def test_restore_roundtrip():
    det = Detector(DetectorConfig())
    for t in range(0, 1200, 30):
        det.update(t, 800)
    clone = Detector(DetectorConfig())
    clone.restore(det.to_dict())
    ev = clone.update(1200, 2) + clone.tick(2000)
    assert types(ev) == [EventType.FINISHED]
    assert abs(ev[0].cycle.energy_wh - 800 * 1200 / 3600) < 1


def test_program_end_finishes_despite_anti_crease():
    cfg = DetectorConfig()
    det = Detector(cfg, program_end_fn=lambda t: t >= 3600)
    crease = [(300, 140), (60, 20), (300, 340), (60, 20)] * 3
    events, t = [], 0.0
    for dur, watts in [(3600, 2000)] + crease + [(2400, 3)]:
        end = t + dur
        while t < end:
            events += det.update(t, watts)
            t += 30
    assert types(events) == [EventType.STARTED, EventType.FINISHED]
    assert events[1].reason == FinishReason.PROGRAM_END
    assert events[1].ts == 3600
    assert det.phase == Phase.FINISHED
    assert det.crease_active_at is None  # quiet long enough afterwards


def test_heating_starts_new_cycle_during_anti_crease():
    det = Detector(DetectorConfig(), program_end_fn=lambda t: 3600 <= t < 3700)
    events, t = [], 0.0
    for dur, watts in [(3600, 2000), (300, 140), (60, 3), (600, 2000)]:
        end = t + dur
        while t < end:
            events += det.update(t, watts)
            t += 30
    assert types(events) == [
        EventType.STARTED, EventType.FINISHED, EventType.CLEARED, EventType.STARTED
    ]
    assert events[2].reason == FinishReason.NEW_CYCLE


def test_motion_after_program_end_is_tracked():
    det = Detector(DetectorConfig(), program_end_fn=lambda t: t >= 3600)
    t = 0.0
    for dur, watts in [(3600, 2000), (300, 140), (600, 3)]:
        end = t + dur
        while t < end:
            det.update(t, watts)
            t += 30
    assert det.phase == Phase.FINISHED
    assert det.motion_at == 3870


def test_bursts_with_single_low_samples_keep_cycle_alive():
    """Real washer 31.10.: light load tumbling, a low sample every ~2 minutes."""
    tumble = [(90, 40), (30, 4), (120, 40), (30, 4)] * 4
    _, ev = run([(1800, 300), (30, 4)] + tumble + [(1200, 4)])
    assert types(ev) == [EventType.STARTED, EventType.FINISHED]
    assert ev[1].cycle.end == 1800 + 30 + 4 * 270 - 30


def test_dip_merge_does_not_join_anti_crease_pulses():
    tail = [(60, 130), (120, 2)] * 15
    _, ev = run([(3000, 150), (120, 2)] + tail + [(600, 2)], DetectorConfig(end_delay_s=240))
    assert types(ev) == [EventType.STARTED, EventType.FINISHED]
    assert ev[1].cycle.end == 3000


def test_restore_during_dip():
    det = Detector(DetectorConfig())
    for t in range(0, 600, 30):
        det.update(float(t), 300.0)
    det.update(600.0, 4.0)
    assert det.run_dip_since == 600.0
    other = Detector(DetectorConfig())
    other.restore(det.to_dict())
    assert other.run_dip_since == 600.0
    other.update(630.0, 300.0)
    assert other.run_dip_since is None and other.run_start is not None
