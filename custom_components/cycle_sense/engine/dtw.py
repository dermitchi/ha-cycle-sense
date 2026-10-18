"""Dynamic time warping on binned power traces.

Programs of the same kind never look identical: heating takes longer with
cold water, load sensing stretches the wash phase. DTW aligns two traces
while allowing such local stretching, so the distance reflects the *shape*
of a program rather than exact timing.

Power is compared on a log scale (``feature``) so that a 2 kW heater does
not drown out the 100 W wash/drum phases that actually tell programs apart.
The symmetric2 step pattern is used, which makes the accumulated cost
comparable after dividing by ``n + m``.
"""

from __future__ import annotations

from collections.abc import Sequence
import math

INF = math.inf
TIE_EPS = 0.005


def feature(power: float) -> float:
    """Map watts to the log-scale feature used for matching."""
    return math.log1p(max(power, 0.0) / 10.0)


def features(trace: Sequence[float]) -> list[float]:
    """Map a whole trace."""
    return [feature(p) for p in trace]


def _band(i: int, m: int) -> tuple[int, int]:
    """Template indices reachable from observed index ``i`` (open end)."""
    lo = max(0, int(i * 0.75) - 5)
    hi = min(m - 1, int(math.ceil(i * 1.33)) + 5)
    return min(lo, m - 1), hi


class StreamingDTW:
    """Open-end DTW of a growing observation against a fixed template.

    Each ``push`` adds one observed bin in O(band) time. Afterwards
    ``distance`` is the normalised cost of the best alignment of everything
    observed so far with *some prefix* of the template, and ``position`` is
    the template index that prefix ends at – i.e. how far into the program
    the appliance currently is.
    """

    def __init__(self, template: Sequence[float]) -> None:
        """Initialize with template features."""
        self.template = list(template)
        self.m = len(self.template)
        self.i = -1
        self._prev: list[float] | None = None
        self.distance = INF
        self.position = 0

    def push(self, x: float) -> None:
        """Add one observed feature value."""
        if not self.m:
            return
        t = self.template
        i = self.i + 1
        lo, hi = _band(i, self.m)
        prev = self._prev
        row = [INF] * self.m
        for j in range(lo, hi + 1):
            c = abs(x - t[j])
            if i == 0 and j == 0:
                row[j] = 2 * c
                continue
            best = INF
            if prev is not None:
                if prev[j] + c < best:
                    best = prev[j] + c
                if j > 0 and prev[j - 1] + 2 * c < best:
                    best = prev[j - 1] + 2 * c
            if j > 0 and row[j - 1] + c < best:
                best = row[j - 1] + c
            row[j] = best
        self._prev = row
        self.i = i
        norm = [(row[j] / (i + j + 2), j) for j in range(lo, hi + 1)]
        best_d = min(d for d, _ in norm)
        # Inside a flat phase (heating, spinning) many template positions fit
        # equally well; then assume normal pace and take the one closest to
        # the elapsed time.
        self.position = min(
            (j for d, j in norm if d <= best_d + TIE_EPS), key=lambda j: abs(j - i)
        )
        self.distance = best_d


def dtw_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Normalised full DTW distance between two feature sequences."""
    n, m = len(a), len(b)
    if not n or not m:
        return INF
    w = max(8, int(0.15 * max(n, m)), abs(n - m) + 3)
    prev = [INF] * m
    for i in range(n):
        row = [INF] * m
        center = i * (m - 1) / max(1, n - 1)
        lo = max(0, int(center - w))
        hi = min(m - 1, int(center + w) + 1)
        for j in range(lo, hi + 1):
            c = abs(a[i] - b[j])
            if i == 0 and j == 0:
                row[j] = 2 * c
                continue
            best = prev[j] + c
            if j > 0:
                best = min(best, prev[j - 1] + 2 * c, row[j - 1] + c)
            row[j] = best
        prev = row
    return prev[m - 1] / (n + m)
