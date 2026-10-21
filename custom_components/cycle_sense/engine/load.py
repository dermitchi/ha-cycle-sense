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
