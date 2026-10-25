"""Remaining time of a running cycle, and whether it can be trusted yet.

Early in a run the shape match only knows which program it is, not how
long this run will take: sensor-dried laundry is done when it is dry
(real Schranktrocknen 18–56 min) and a washer with load sensing rinses
longer for more laundry (real Koch-/Buntwäsche 40° 46–85 min). Telling
“about 37 min” too early and correcting it later is worse than saying
“still working it out” for a while.

So the estimate comes from the program's other runs that are still
possible: runs shorter than what has already passed are ruled out. The
time is *reliable* once most runs are still possible and agree closely.
After the heating, the rest of a program (rinse, spin, cooling) is about
the same in most runs, so many programs become reliable there at the
latest.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from .load import blend_remaining, heating_over, predict_duration, predict_energy, tail_bins

AGREE_S = 240.0
"""Runs that end this close together always agree."""
AGREE_SHARE = 0.2
"""… or within this share of the time still to go."""
MIN_RUNS = 3
"""Runs needed to judge agreement before the heating is over (two may agree by chance)."""


@dataclass(frozen=True)
class Run:
    """What the estimate needs from one recorded run of the program."""

    duration_s: float
    tail_bins: int | None
    energy_wh: float
    load: float | None = None


@dataclass(frozen=True)
class Eta:
    """Remaining seconds and whether they are good enough to show."""

    remaining_s: float
    reliable: bool


def _agree(left_s: Sequence[float], known: int) -> bool:
    """True if the runs still possible end close together.

    They must also be most of the program's runs: when a run outlives the
    usual ones, the few longer runs left say little about this one (real
    Koch-/Buntwäsche 40°: tails of 36–50 and 71–72 min).
    """
    if 2 * len(left_s) < known:
        return False
    spread = max(left_s) - min(left_s)
    return spread <= max(AGREE_S, AGREE_SHARE * median(left_s))


def _load_total(trace: Sequence[float], bin_s: int, runs: Sequence[Run], load: float) -> float | None:
    """Run length for a known load, unless this run already outgrew it.

    A load that is set too low (or wetter laundry) would count down to zero
    while the appliance is still heating, then jump. More energy than a
    whole run of that load takes means the prediction is off.
    """
    total = predict_duration(load, [(r.load, r.duration_s) for r in runs])
    if total is None:
        return None
    energy = predict_energy(load, [(r.load, r.energy_wh) for r in runs])
    used = sum(trace) * bin_s / 3600
    if energy is not None and used > energy:
        return None
    return total


def estimate(
    shape_s: float,
    trace: Sequence[float],
    bin_s: int,
    runs: Sequence[Run],
    load: float | None = None,
) -> Eta:
    """Remaining time of a run of a (confidently) recognised program."""
    elapsed = len(trace) * bin_s
    if heating_over(trace):
        tails = [r.tail_bins for r in runs if r.tail_bins is not None]
        if tails:
            done = tail_bins(trace) or 0
            left = [(t - done) * bin_s for t in tails if t >= done]
            if left:
                rest = median(left)
                if _agree(left, len(tails)):
                    return Eta(rest, True)
                return Eta(blend_remaining(shape_s, elapsed + rest, elapsed), False)
    left = [r.duration_s - elapsed for r in runs if r.duration_s >= elapsed]
    reliable = len(left) >= MIN_RUNS and _agree(left, len(runs))
    if load is not None and (total := _load_total(trace, bin_s, runs, load)) is not None:
        return Eta(blend_remaining(shape_s, total, elapsed), reliable)
    if reliable:
        # Agreeing runs beat the shape match, which is noisy in flat phases.
        return Eta(median(left), True)
    return Eta(shape_s, False)
