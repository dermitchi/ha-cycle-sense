"""Current program phase (wash, rinse, spin …) from the power draw.

Calibrated on a real washer run whose panel was read along (Pflegeleicht
40°): heating ~2000 W and drum turns 50–150 W while *washing*, a few
minutes at 5–40 W while *pumping*, drum turns again while *rinsing*
(short pumps in between keep the panel on rinsing), then the *final spin*
ramps 60 → 240 W and the panel shows *end* as soon as power drops. Some
rinses also spin up to ~200 W, so a spin only counts as the final one
near the end of a recognised program or after a long rinse.

Dryers: heating ~2400 W (the thermostat pauses it for a minute now and
then), *cooling* is the drum alone (~130 W) for the last minutes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

OFF = "off"
WASH = "wash"
PUMP = "pump"
RINSE = "rinse"
FINAL_SPIN = "final_spin"
DRY = "drying"
COOL = "cooling"
END = "end"
ALL_PHASES = [OFF, WASH, PUMP, RINSE, FINAL_SPIN, DRY, COOL, END]

HEAT_W = 1000.0
PUMP_MAX_W = 45.0
PUMP_MIN_W = 5.0
PUMP_MIN_S = 30.0
"""Pumping must last this long (shorter dips are pauses of the drum)."""
SPIN_W = 180.0
FINAL_SPIN_PROGRESS = 0.85
FINAL_SPIN_AFTER_RINSE_S = 600.0
"""Without a recognised program, spin counts as final after this much rinsing."""
RINSE_AFTER_S = 60.0
DRUM_RESUMES_S = 120.0
"""Drum turns this long after a spin: it was not the final spin."""
END_AFTER_SPIN_S = 60.0
"""Washer: quiet this long after the final spin – the panel shows *end*."""
COOL_AFTER_S = 180.0
"""Dryer: no heating for this long means it is cooling down."""
MIN_WASH_S = 600.0


@dataclass
class PhaseState:
    """Persisted tracker state."""

    phase: str = OFF
    start: float | None = None
    last_heat: float | None = None
    low_since: float | None = None
    rinse_since: float | None = None
    drum_since: float | None = None


class PhaseTracker:
    """Follows the program phase of one cycle."""

    def __init__(self, appliance: str) -> None:
        """Initialize for 'washer' or 'dryer' (others get no phases)."""
        self.appliance = appliance
        self.state = PhaseState()

    @property
    def phase(self) -> str | None:
        """Current phase, or None for appliances without phase support."""
        if self.appliance not in ("washer", "dryer"):
            return None
        return self.state.phase

    def update(
        self, ts: float, power: float, running: bool, finished: bool, progress: float | None
    ) -> str | None:
        """Feed a power reading with the cycle state; returns the phase."""
        st = self.state
        if not running:
            self.state = PhaseState(phase=END if finished else OFF)
            return self.phase
        if st.start is None:
            self.state = st = PhaseState(phase=WASH if self.appliance == "washer" else DRY, start=ts)
        if power > HEAT_W:
            st.last_heat = ts
        if self.appliance == "washer":
            self._washer(ts, power, progress)
        elif self.appliance == "dryer":
            self._dryer(ts, power)
        return self.phase

    def _washer(self, ts: float, power: float, progress: float | None) -> None:
        st = self.state
        low = PUMP_MIN_W <= power <= PUMP_MAX_W
        if low:
            st.low_since = st.low_since or ts
        elif power < PUMP_MIN_W:
            pass  # drum pause: keep any pumping that is going on
        else:
            st.low_since = None
        drum = PUMP_MAX_W < power < SPIN_W
        st.drum_since = (st.drum_since or ts) if drum else None

        if power >= SPIN_W and power <= HEAT_W and st.phase in (RINSE, PUMP):
            near_end = progress is not None and progress >= FINAL_SPIN_PROGRESS
            long_rinse = (
                progress is None
                and st.rinse_since is not None
                and ts - st.rinse_since >= FINAL_SPIN_AFTER_RINSE_S
            )
            if near_end or long_rinse:
                st.phase = FINAL_SPIN
                return
        if (
            st.phase in (FINAL_SPIN, END)
            and st.drum_since is not None
            and ts - st.drum_since >= DRUM_RESUMES_S
        ):
            # Rinsing goes on: that spin was an intermediate one.
            st.phase = RINSE
            return
        if st.phase == FINAL_SPIN:
            # The panel shows "end" right after spinning; the cycle itself
            # is only reported finished after the usual quiet time.
            if power <= PUMP_MAX_W:
                st.low_since = st.low_since or ts
                if ts - st.low_since >= END_AFTER_SPIN_S:
                    st.phase = END
            return
        if st.phase == END:
            return

        pumping = st.low_since is not None and ts - st.low_since >= PUMP_MIN_S
        if st.phase == WASH:
            if pumping and st.start is not None and ts - st.start >= MIN_WASH_S and power <= HEAT_W:
                st.phase = PUMP
        elif st.phase == PUMP:
            # The spin-up after the last pump starts slowly; only a drum
            # that keeps turning means rinsing.
            if st.drum_since is not None and ts - st.drum_since >= RINSE_AFTER_S:
                st.phase = RINSE
                st.rinse_since = st.rinse_since or ts
        elif st.phase == RINSE:
            # The panel stays on rinsing during the pumps between rinses;
            # only the last pump before the final spin shows as pumping.
            if pumping and progress is not None and progress >= FINAL_SPIN_PROGRESS:
                st.phase = PUMP

    def _dryer(self, ts: float, power: float) -> None:
        st = self.state
        if power > HEAT_W:
            st.phase = DRY
        elif st.last_heat is not None and ts - st.last_heat >= COOL_AFTER_S:
            st.phase = COOL

    def to_dict(self) -> dict[str, Any]:
        """Serialize."""
        return asdict(self.state)

    def restore(self, data: dict[str, Any] | None) -> None:
        """Restore persisted state."""
        if data:
            self.state = PhaseState(**{k: v for k, v in data.items() if k in PhaseState.__annotations__})
