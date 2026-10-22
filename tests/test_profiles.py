"""Learning, grouping and live recognition."""

import random

from engine import Matcher, ProfileStore, Sample
from engine.profiles import MAX_SAMPLES


def wash(minutes_heat=15, minutes_wash=40, minutes_spin=8, jitter=0.0, seed=0):
    """Synthetic washer trace: heat, wash with dips, spin."""
    rng = random.Random(seed)
    trace = [80.0] * 2 + [2000.0] * minutes_heat
    for k in range(minutes_wash):
        trace.append(3.0 if k % 9 == 4 else 100.0 + rng.uniform(-jitter, jitter) * 100)
    trace += [400.0] * minutes_spin
    return trace


def dry(minutes_heat=40, seed=0):
    rng = random.Random(seed)
    return [130.0] + [2600.0 if rng.random() > 0.15 else 130.0 for _ in range(minutes_heat)] + [130.0] * 10


_counter = iter(range(10**6))


def sample(trace, recorded=None, source="auto"):
    if recorded is None:
        recorded = 1000.0 + next(_counter)
    return Sample(trace, len(trace) * 60.0, sum(trace) / 60, recorded, source)


def test_named_learning_and_classification():
    store = ProfileStore()
    res = store.learn(sample(wash(seed=1), 1), name="Baumwolle 40")
    assert res.profile == "Baumwolle 40" and res.created
    res = store.learn(sample(wash(seed=2, jitter=0.1), 2))
    assert res.profile == "Baumwolle 40"
    assert len(store.get("baumwolle 40").samples) == 2


def test_different_program_is_not_merged():
    store = ProfileStore()
    store.learn(sample(wash(), 1), name="Baumwolle 40")
    res = store.learn(sample(dry(), 2))
    assert res.profile is None
    assert len(store.unassigned) == 1


def test_auto_grouping_creates_program():
    store = ProfileStore()
    assert store.learn(sample(dry(seed=1), 1)).profile is None
    res = store.learn(sample(dry(seed=2), 2), auto_name_fmt="Programm {n}")
    assert res.created and res.profile == "Programm 1"
    assert store.unassigned == []


def test_explicit_learn_moves_run():
    store = ProfileStore()
    store.learn(sample(dry(seed=1), 1))
    store.learn(sample(dry(seed=2), 2), auto_name_fmt="P{n}")
    assert store.get("P1") is not None
    store.learn(sample(dry(seed=2), 2), name="Schranktrocken")
    assert len(store.get("P1").samples) == 1
    assert len(store.get("Schranktrocken").samples) == 1


def test_rename_merges_and_delete():
    store = ProfileStore()
    store.learn(sample(wash(seed=1), 1), name="A")
    store.learn(sample(dry(seed=1), 2), name="B")
    assert store.rename("B", "a")
    assert store.names() == ["A"] and len(store.get("A").samples) == 2
    assert store.delete("A") and store.profiles == []


def test_scanned_samples_survive_trimming():
    store = ProfileStore()
    store.learn(sample(wash(seed=0), 0, "learn"), name="X")
    for k in range(1, MAX_SAMPLES + 3):
        store.add_sample("X", sample(wash(seed=k), k))
    assert any(s.source == "learn" for s in store.get("X").samples)
    assert len(store.get("X").samples) == MAX_SAMPLES


def test_live_recognition_and_remaining_time():
    store = ProfileStore()
    store.learn(sample(wash(minutes_wash=40, seed=1)), name="Kurz")
    store.learn(sample(dry(seed=1)), name="Trocknen")
    matcher = Matcher(store, 60, 8)
    matcher.reset()
    run = wash(minutes_wash=40, seed=5, jitter=0.05)
    for p in run[:30]:
        matcher.push(p)
    best = matcher.best()
    assert best is not None and best.profile.name == "Kurz"
    assert best.confidence > 0.6
    assert abs(best.remaining_s / 60 - (len(run) - 30)) <= 6


def test_unknown_run_is_not_confident():
    store = ProfileStore()
    store.learn(sample(dry(seed=1)), name="Trocknen")
    matcher = Matcher(store, 60, 8)
    matcher.reset()
    for p in [60.0] * 30:
        matcher.push(p)
    best = matcher.best()
    assert best is None or best.confidence < 0.4


def test_end_delay_waits_for_learned_pause():
    # Program with a 20 min soak in the middle.
    soak = [100.0] * 20 + [2.0] * 20 + [100.0] * 20
    store = ProfileStore()
    store.learn(sample(soak), name="Einweichen")
    matcher = Matcher(store, 60, 8)
    matcher.reset()
    for p in soak[:21]:
        matcher.push(p)
    assert matcher.end_delay(300, 120, 2700) > 20 * 60


def test_end_delay_short_at_program_end():
    trace = wash(seed=3)
    store = ProfileStore()
    store.learn(sample(trace), name="Normal")
    matcher = Matcher(store, 60, 8)
    matcher.reset()
    for p in trace:
        matcher.push(p)
    assert matcher.end_delay(300, 120, 2700) == 120


def test_end_delay_default_when_unsure():
    store = ProfileStore()
    matcher = Matcher(store, 60, 8)
    matcher.reset()
    for p in wash()[:20]:
        matcher.push(p)
    assert matcher.end_delay(300, 120, 2700) == 300


def test_store_roundtrip():
    store = ProfileStore()
    store.learn(sample(wash(seed=1), 1), name="A")
    store.learn(sample(dry(seed=1), 2))
    clone = ProfileStore.from_dict(store.to_dict())
    assert clone.names() == ["A"] and len(clone.unassigned) == 1
    assert clone.get("A").template == store.get("A").template


def test_program_end_only_at_learned_length():
    store = ProfileStore()
    store.add_sample("P", sample(wash(), source="learn"))
    m = Matcher(store, 60, 8)
    m.reset()
    run = wash(seed=1) + [140.0] * 20
    m_len = len(store.profiles[0].template)
    hits = []
    for k, p in enumerate(run, 1):
        m.push(p)
        if m.program_end_reached():
            hits.append(k)
    assert hits and hits[0] == m_len
    assert max(hits) <= m_len + 3


def test_program_end_not_for_longer_program():
    store = ProfileStore()
    store.add_sample("Short", sample(wash(minutes_wash=30), source="learn"))
    m = Matcher(store, 60, 8)
    m.reset()
    run = wash(minutes_wash=30, minutes_spin=0) + [100.0] * 30 + [400.0] * 8
    hits = []
    for p in run:
        m.push(p)
        hits.append(m.program_end_reached())
    m_len = len(store.profiles[0].template)
    assert not any(hits[m_len + 3 :])


def test_near_end_rule_not_for_much_longer_run():
    store = ProfileStore()
    store.add_sample("P", sample(wash(minutes_wash=30), source="learn"))
    m = Matcher(store, 60, 8)
    m.reset()
    m_len = len(store.profiles[0].template)
    for p in wash(minutes_wash=30, minutes_spin=0) + [100.0] * 30:
        m.push(p)
    assert m.n > m_len + 3
    assert m.end_delay(300, 120, 2700) == 300


def test_clear_unassigned():
    store = ProfileStore()
    store.learn(sample(wash()))
    assert store.clear_unassigned() == 1
    assert store.unassigned == []


def test_shown_program_holds_steady():
    """Programs that start alike must not make the display flip every bin."""
    store = ProfileStore()
    store.learn(sample([130.0] + [2600.0] * 8 + [130.0] * 3, 1), name="Kurz")
    store.learn(sample([130.0] + [2600.0] * 40 + [130.0] * 10, 2), name="Lang")
    m = Matcher(store, 60, 10)
    m.reset()
    shown = []
    for p in [130.0] + [2600.0] * 30:
        m.push(p)
        s = m.shown()
        shown.append(s.profile.name if s else None)
    changes = sum(1 for a, b in zip(shown, shown[1:]) if a != b)
    assert shown[-1] == "Lang"
    assert changes <= 2
    assert None not in shown[shown.index("Lang") :]


def test_shown_program_is_stored():
    store = ProfileStore()
    store.learn(sample(dry(minutes_heat=18, seed=1), 1), name="Schranktrocknen")
    store.learn(sample(dry(minutes_heat=18, seed=2), 2), name="20 Min warm")
    res = store.learn(sample(dry(minutes_heat=18, seed=3), 3), shown="20 Min warm")
    assert res.profile == "20 Min warm"
    assert len(store.get("20 Min warm").samples) == 2
    assert len(store.get("Schranktrocknen").samples) == 1


def test_move_recording_by_start_time():
    store = ProfileStore()
    store.learn(sample(dry(seed=1), 1000.0), name="Schranktrocknen")
    store.learn(sample(dry(seed=2), 5000.0), name="Schranktrocknen")
    assert store.move_recording(5100.0, "20 Min warm").name == "20 Min warm"
    assert [s.recorded for s in store.get("Schranktrocknen").samples] == [1000.0]
    assert store.move_recording(9000.0, "20 Min warm") is None
