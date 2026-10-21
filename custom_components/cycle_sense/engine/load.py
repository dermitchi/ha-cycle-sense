"""Estimate how full the drum was from the heating energy of a run.

Washers with automatic load sensing take in more water for more laundry,
so the heater runs longer; a sensor-controlled dryer heats until the
laundry is dry, so more (wet) laundry also means more heating. Comparing a
run with calibrated runs of the *same* program cancels the program's own
temperature and timing.

Measured on real runs (Pflegeleicht 40°): full drum 336 Wh heating, a
partial load 183 Wh. Even an empty run heats some water, hence the
base share instead of a line through zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import median

HEAT_BASE_W = 300.0
"""Power drawn by motor/drum; everything above counts as heating."""
HEAT_ACTIVE_W = 1000.0
"""A bin above this is mostly heating."""
BASE_SHARE = {"washer": 0.3, "dryer": 0.1}
"""Heating share of an (almost) empty drum relative to a full one."""
DEFAULT_BASE_SHARE = 0.2
MIN_SPREAD = 0.2
"""Calibrated loads must differ this much for a line fit."""
MIN_LOAD = 0.05
MAX_LOAD = 1.0
LEVELS = ((0.45, "low"), (0.8, "half"), (2.0, "full"))
SETTLED_BINS = 3
"""Bins without heating before the heating phase counts as over."""
MODEL_TRUST_UNTIL = 0.75
"""Fraction of the predicted run after which the shape match takes over."""


def heat_wh(trace: Sequence[float], bin_s: int) -> float:
    """Heating energy of a run (power above the motor level), in Wh."""
    return sum(max(0.0, p - HEAT_BASE_W) for p in trace) * bin_s / 3600


def heating_end(trace: Sequence[float]) -> int | None:
    """Index of the last bin that is mostly heating, or None."""
    hot = [k for k, p in enumerate(trace) if p > HEAT_ACTIVE_W]
    return hot[-1] if hot else None


def level(load: float) -> str:
    """Coarse level for display."""
    return next(name for limit, name in LEVELS if load < limit)


@dataclass
class LoadEstimate:
    """How full the drum was."""

    load: float
    basis: str
    """'line' (two or more calibrated loads) or 'single' (one)."""
    points: int

    @property
    def level(self) -> str:
        """Coarse level."""
        return level(self.load)


def estimate(
    heat: float, points: Iterable[tuple[float, float]], base_share: float = DEFAULT_BASE_SHARE
) -> LoadEstimate | None:
    """Load (0..1) for ``heat`` from calibrated ``(load, heat)`` points of one program."""
    pts = [(l, h) for l, h in points if h > 0]
    if not pts:
        return None
    loads = [l for l, _ in pts]
    if len(pts) >= 2 and max(loads) - min(loads) >= MIN_SPREAD:
        n = len(pts)
        ml = sum(loads) / n
        mh = sum(h for _, h in pts) / n
        sxx = sum((l - ml) ** 2 for l in loads)
        slope = sum((l - ml) * (h - mh) for l, h in pts) / sxx
        if slope > 0:
            value = ml + (heat - mh) / slope
            return LoadEstimate(_clamp(value), "line", n)
    # One calibration (or a useless fit): scale from the closest point,
    # assuming the empty drum still heats base_share of a full one.
    l0, h0 = min(pts, key=lambda p: abs(p[1] - heat))
    full = h0 / (base_share + (1 - base_share) * l0)
    value = (heat / full - base_share) / (1 - base_share)
    return LoadEstimate(_clamp(value), "single", len(pts))


def _clamp(value: float) -> float:
    return min(MAX_LOAD, max(MIN_LOAD, value))


def heating_over(trace: Sequence[float]) -> bool:
    """True once the run has heated and then not heated for a few bins."""
    end = heating_end(trace)
    return end is not None and len(trace) - 1 - end >= SETTLED_BINS


def tail_bins(trace: Sequence[float]) -> int | None:
    """Bins after the last heating bin (rinsing, spinning, cooling down)."""
    end = heating_end(trace)
    return None if end is None else len(trace) - 1 - end


def predict_remaining(trace: Sequence[float], tails: Iterable[int], bin_s: int) -> float | None:
    """Remaining seconds once heating is over, from the program's usual tail.

    Less laundry shortens the heating, while what follows the last heating
    (rinse, spin) takes about the same time in every run of a program
    (real Pflegeleicht 40° runs: 59 / 45 min long, tails 35 / 38 min).
    """
    known = [t for t in tails if t is not None]
    if not known or not heating_over(trace):
        return None
    tail = median(known)
    done = tail_bins(trace) or 0
    return max(0.0, (tail - done) * bin_s)


def predict_duration(load: float, points: Iterable[tuple[float | None, float]]) -> float | None:
    """Run length in s for ``load`` from ``(load, duration_s)`` of runs of one program.

    Sensor-dried laundry is done when it is dry, so the run scales with how
    much (wet) laundry there is (real Schranktrocknen: full ~56 min, a
    third ~18 min). Shape matching alone always assumes the template's load.
    """
    pts = [(l, d) for l, d in points if l is not None and d > 0]
    if not pts:
        return None
    loads = [l for l, _ in pts]
    if len(pts) >= 2 and max(loads) - min(loads) >= MIN_SPREAD:
        n = len(pts)
        ml = sum(loads) / n
        md = sum(d for _, d in pts) / n
        sxx = sum((l - ml) ** 2 for l in loads)
        slope = sum((l - ml) * (d - md) for l, d in pts) / sxx
        if slope > 0:
            return max(min(d for _, d in pts) * 0.5, md + slope * (load - ml))
    # One run, or loads too close: no way to tell a timed program (same
    # length whatever the load) from a sensor-controlled one.
    return None


def blend_remaining(shape_s: float, predicted_s: float, elapsed_s: float) -> float:
    """Remaining time: the load-based prediction first, the shape match near the end."""
    model = predicted_s - elapsed_s
    if model <= 0:
        return shape_s
    start = MODEL_TRUST_UNTIL * predicted_s
    weight = 1.0 if elapsed_s <= start else max(0.0, model / (predicted_s - start))
    return weight * model + (1 - weight) * shape_s
