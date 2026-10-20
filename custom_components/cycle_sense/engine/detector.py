"""Cycle state machine driven by a power signal.

The detector is fed with power samples (``update``) and with the passage of
time (``tick``). It treats the signal as a step function: a value holds
until the next sample arrives. All timers are evaluated at their exact
deadline, so replaying sparse recorded data gives the same result as a live
run with frequent ticks.

Phases::

    OFF ──(sustained power > start_power)──▶ RUNNING
    RUNNING ──(no significant activity for the end delay)──▶ FINISHED
    FINISHED ──(door / switched off / acknowledged / timeout / new cycle)──▶ OFF

"Significant activity" is any stretch above ``end_power`` that lasts longer
than ``spike_max_s``. Shorter bursts – the anti-crease drum turns of a dryer
or the post-spin twitches of a washer – neither keep a cycle alive nor start
a new one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, fields
from enum import StrEnum
import math
from typing import Any


class Phase(StrEnum):
    """Externally visible appliance phase."""

    OFF = "off"
    RUNNING = "running"
    FINISHED = "finished"


class EventType(StrEnum):
    """Events emitted by the detector."""

    STARTED = "started"
    FINISHED = "finished"
    ABORTED = "aborted"
    CLEARED = "cleared"


class FinishReason(StrEnum):
    """Why a cycle ended or a finished state was cleared."""

    QUIET = "quiet"
    PROGRAM_END = "program_end"
    SWITCHED_OFF = "switched_off"
    UNAVAILABLE = "unavailable"
    FORCED = "forced"
    TOO_SHORT = "too_short"
    RESTORE_GAP = "restore_gap"
    DOOR = "door"
    ACKNOWLEDGED = "acknowledged"
    TIMEOUT = "timeout"
    NEW_CYCLE = "new_cycle"


@dataclass
class DetectorConfig:
    """Tuning parameters. Times in seconds, power in watts."""

    start_power: float = 50.0
    start_confirm_s: float = 120.0
    start_dropout_s: float = 60.0
    end_power: float = 8.0
    spike_max_s: float = 150.0
    end_delay_s: float = 300.0
    off_power: float = 0.5
    off_confirm_s: float = 30.0
    min_cycle_s: float = 300.0
    finished_timeout_s: float = 0.0
    unavailable_abort_s: float = 3600.0
    crease_start_power: float = 1000.0
    crease_quiet_s: float = 1200.0
    bin_s: int = 60

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DetectorConfig:
        """Build a config, ignoring unknown keys."""
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class CycleRecord:
    """Power trace and metadata of one cycle."""

    start: float
    bin_s: int = 60
    bins: list[float] = field(default_factory=list)
    energy_wh: float = 0.0
    peak_w: float = 0.0
    end: float | None = None
    finished_at: float | None = None
    reason: str | None = None
    acc_ws: float = 0.0
    acc_s: float = 0.0
    covered_s: float = 0.0

    def add(self, t0: float, t1: float, power: float | None) -> None:
        """Integrate a constant power over [t0, t1); None marks a data gap."""
        t0 = max(t0, self.start)
        while t0 < t1:
            bin_end = self.start + (len(self.bins) + 1) * self.bin_s
            seg_end = min(t1, bin_end)
            dt = seg_end - t0
            if power is not None:
                self.acc_ws += power * dt
                self.acc_s += dt
                self.energy_wh += power * dt / 3600.0
            self.covered_s += dt
            t0 = seg_end
            if seg_end >= bin_end:
                self._close_bin()

    def _close_bin(self) -> None:
        if self.acc_s > 0:
            value = self.acc_ws / self.acc_s
        else:
            value = self.bins[-1] if self.bins else 0.0
        self.bins.append(round(value, 2))
        self.acc_ws = 0.0
        self.acc_s = 0.0

    @property
    def duration_s(self) -> float:
        """Duration of the active part (or so far)."""
        end = self.end if self.end is not None else self.start + self.covered_s
        return max(0.0, end - self.start)

    def trace(self, until: float | None = None) -> list[float]:
        """Binned trace up to ``until`` (default: end of activity)."""
        until = self.end if until is None else until
        out = list(self.bins)
        if self.acc_s > 0:
            out.append(round(self.acc_ws / self.acc_s, 2))
        if until is None:
            return out
        n = max(1, math.ceil((until - self.start) / self.bin_s))
        return out[:n]

    def to_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CycleRecord:
        """Deserialize."""
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class DetectorEvent:
    """A state change worth telling the outside world about."""

    type: EventType
    ts: float
    reason: FinishReason | None = None
    cycle: CycleRecord | None = None


EndDelayFn = Callable[[float, float], float]
"""(quiet_since, now) -> seconds of quiet required before finishing."""
ProgramEndFn = Callable[[float], bool]
"""(now) -> True once a recognised program has reached its learned end."""


class Detector:
    """Deterministic cycle state machine."""

    def __init__(
        self,
        config: DetectorConfig,
        end_delay_fn: EndDelayFn | None = None,
        program_end_fn: ProgramEndFn | None = None,
    ) -> None:
        self.config = config
        self.end_delay_fn = end_delay_fn
        self.program_end_fn = program_end_fn
        self.phase = Phase.OFF
        self.cycle: CycleRecord | None = None
        self.last_cycle: CycleRecord | None = None
        self.last_ts: float | None = None
        self.power: float | None = None
        self.available = True
        self.unavailable_since: float | None = None
        self.cand_start: float | None = None
        self.cand_below_since: float | None = None
        self.run_start: float | None = None
        self.run_significant = False
        self.last_active: float | None = None
        self.off_since: float | None = None
        self.finished_since: float | None = None
        # Set when a cycle ended at its learned program end while the
        # appliance kept moving (anti-crease). Until it has been quiet for a
        # while, only heating-level power may start a new cycle.
        self.crease_active_at: float | None = None

    # ------------------------------------------------------------------ API

    @property
    def candidate(self) -> bool:
        """True while a possible start is being confirmed."""
        return self.cand_start is not None

    def update(self, ts: float, power: float | None) -> list[DetectorEvent]:
        """Feed a new sample. ``None`` means the sensor is unavailable."""
        events: list[DetectorEvent] = []
        if self.last_ts is not None and ts < self.last_ts:
            return events
        self._advance(ts, events)
        if power is None or math.isnan(power):
            if self.available:
                self.available = False
                self.unavailable_since = ts
            return events
        if not self.available:
            self.available = True
            self.unavailable_since = None
        self.power = power
        self._apply(ts, power, events)
        self._evaluate(ts, events)
        return events

    def tick(self, ts: float) -> list[DetectorEvent]:
        """Advance time without a new sample."""
        events: list[DetectorEvent] = []
        if self.last_ts is not None and ts >= self.last_ts:
            self._advance(ts, events)
        return events

    def quiet_since(self, now: float) -> float | None:
        """Start of the current quiet stretch while running, else None."""
        if self.phase != Phase.RUNNING or self.run_start is not None:
            return None
        return self.last_active

    def acknowledge(self, ts: float) -> list[DetectorEvent]:
        """User confirmed the appliance was emptied."""
        events: list[DetectorEvent] = []
        self._advance(ts, events)
        self._clear(ts, FinishReason.ACKNOWLEDGED, events)
        return events

    def door_opened(self, ts: float) -> list[DetectorEvent]:
        """Door contact opened."""
        events: list[DetectorEvent] = []
        self._advance(ts, events)
        self._clear(ts, FinishReason.DOOR, events)
        return events

    def force_finish(self, ts: float) -> list[DetectorEvent]:
        """End a running cycle immediately."""
        events: list[DetectorEvent] = []
        self._advance(ts, events)
        if self.phase == Phase.RUNNING:
            self._finish(ts, FinishReason.FORCED, events)
        return events

    def handle_restore(self, now: float, max_gap_s: float) -> list[DetectorEvent]:
        """Drop a running cycle whose data gap after a restart is too large."""
        events: list[DetectorEvent] = []
        if self.last_ts is None or now - self.last_ts <= max_gap_s:
            return events
        if self.phase == Phase.RUNNING and self.cycle is not None:
            cycle = self.cycle
            cycle.end = self._active_end(self.last_ts)
            cycle.finished_at = now
            cycle.reason = FinishReason.RESTORE_GAP
            self._reset_cycle_state()
            self.phase = Phase.OFF
            events.append(
                DetectorEvent(EventType.ABORTED, now, FinishReason.RESTORE_GAP, cycle)
            )
        elif self.candidate:
            self._cancel_candidate()
        # Continue from "now" without integrating the gap.
        self.last_ts = now
        return events

    # ------------------------------------------------------------ internals

    def _end_delay(self, quiet_since: float, now: float) -> float:
        if self.end_delay_fn is None:
            return self.config.end_delay_s
        return max(1.0, float(self.end_delay_fn(quiet_since, now)))

    def _active_end(self, now: float) -> float:
        if self.run_significant:
            return now
        assert self.last_active is not None
        return self.last_active

    def _deadline(self, now: float) -> float | None:
        cfg = self.config
        cands: list[float] = []
        if self.cand_start is not None:
            if self.cand_below_since is not None:
                cands.append(self.cand_below_since + cfg.start_dropout_s)
            else:
                cands.append(self.cand_start + cfg.start_confirm_s)
        if self.phase == Phase.RUNNING:
            if not self.available and self.unavailable_since is not None:
                cands.append(self.unavailable_since + cfg.unavailable_abort_s)
            if self.off_since is not None and self.available:
                cands.append(self.off_since + cfg.off_confirm_s)
            if self.run_start is not None:
                if not self.run_significant:
                    cands.append(self.run_start + cfg.spike_max_s)
            elif self.last_active is not None and self.available:
                cands.append(self.last_active + self._end_delay(self.last_active, now))
        elif self.phase == Phase.FINISHED:
            if self.off_since is not None and self.available:
                cands.append(self.off_since + cfg.off_confirm_s)
            if cfg.finished_timeout_s > 0 and self.finished_since is not None:
                cands.append(self.finished_since + cfg.finished_timeout_s)
            if self.crease_active_at is not None:
                cands.append(self.crease_active_at + cfg.crease_quiet_s)
        return min(cands) if cands else None

    def _integrate(self, ts: float) -> None:
        if self.last_ts is None:
            self.last_ts = ts
            return
        if self.cycle is not None and ts > self.last_ts:
            self.cycle.add(self.last_ts, ts, self.power if self.available else None)
            if self.available and self.power is not None:
                self.cycle.peak_w = max(self.cycle.peak_w, self.power)
        self.last_ts = max(self.last_ts, ts)

    def _advance(self, ts: float, events: list[DetectorEvent]) -> None:
        if self.last_ts is None:
            self.last_ts = ts
            return
        for _ in range(64):
            deadline = self._deadline(self.last_ts)
            if deadline is None or deadline > ts:
                break
            deadline = max(deadline, self.last_ts)
            self._integrate(deadline)
            if not self._evaluate(deadline, events):
                break
        self._integrate(ts)
        self._evaluate(ts, events)

    def _apply(self, ts: float, power: float, events: list[DetectorEvent]) -> None:
        cfg = self.config
        if power <= cfg.off_power:
            if self.off_since is None:
                self.off_since = ts
        else:
            self.off_since = None

        if self.phase in (Phase.OFF, Phase.FINISHED):
            if self.crease_active_at is not None:
                if power > cfg.start_power:
                    self.crease_active_at = ts
                if power <= cfg.crease_start_power:
                    if self.cand_start is not None and self.cand_below_since is None:
                        self.cand_below_since = ts
                    return
            if power > cfg.start_power:
                if self.cand_start is None:
                    self.cand_start = ts
                    self.cycle = CycleRecord(start=ts, bin_s=cfg.bin_s)
                self.cand_below_since = None
            elif self.cand_start is not None and self.cand_below_since is None:
                self.cand_below_since = ts
            return

        # RUNNING
        if self.cycle is not None:
            self.cycle.peak_w = max(self.cycle.peak_w, power)
        if power > cfg.end_power:
            if self.run_start is None:
                self.run_start = ts
                self.run_significant = False
        elif self.run_start is not None:
            if self.run_significant:
                self.last_active = ts
            self.run_start = None
            self.run_significant = False

    def _evaluate(self, t: float, events: list[DetectorEvent]) -> bool:
        """Apply time-based transitions at ``t``. Returns True on change."""
        cfg = self.config

        if self.cand_start is not None:
            if (
                self.cand_below_since is not None
                and t - self.cand_below_since >= cfg.start_dropout_s
            ):
                self._cancel_candidate()
                return True
            if self.cand_below_since is None and t - self.cand_start >= cfg.start_confirm_s:
                self._confirm(t, events)
                return True

        if self.phase == Phase.FINISHED:
            if (
                self.available
                and self.off_since is not None
                and t - self.off_since >= cfg.off_confirm_s
            ):
                self._clear(t, FinishReason.SWITCHED_OFF, events)
                return True
            if (
                cfg.finished_timeout_s > 0
                and self.finished_since is not None
                and t - self.finished_since >= cfg.finished_timeout_s
            ):
                self._clear(t, FinishReason.TIMEOUT, events)
                return True
            if (
                self.crease_active_at is not None
                and self.available
                and (self.power or 0.0) <= cfg.start_power
                and t - self.crease_active_at >= cfg.crease_quiet_s
            ):
                self.crease_active_at = None
                return True
            return False

        if self.phase != Phase.RUNNING:
            return False

        if not self.available:
            if (
                self.unavailable_since is not None
                and t - self.unavailable_since >= cfg.unavailable_abort_s
            ):
                self._finish(t, FinishReason.UNAVAILABLE, events)
                return True
            return False

        if self.off_since is not None and t - self.off_since >= cfg.off_confirm_s:
            self._finish(t, FinishReason.SWITCHED_OFF, events)
            return True

        if self.program_end_fn is not None and self.program_end_fn(t):
            self._finish(t, FinishReason.PROGRAM_END, events)
            return True

        if self.run_start is not None:
            if not self.run_significant and t - self.run_start >= cfg.spike_max_s:
                self.run_significant = True
                return True
            return False

        assert self.last_active is not None
        if t - self.last_active >= self._end_delay(self.last_active, t):
            self._finish(t, FinishReason.QUIET, events)
            return True
        return False

    def _cancel_candidate(self) -> None:
        self.cand_start = None
        self.cand_below_since = None
        self.cycle = None

    def _confirm(self, t: float, events: list[DetectorEvent]) -> None:
        if self.phase == Phase.FINISHED:
            self._clear(t, FinishReason.NEW_CYCLE, events)
        assert self.cycle is not None
        self.phase = Phase.RUNNING
        self.cand_start = None
        self.cand_below_since = None
        self.last_active = t
        if self.power is not None and self.power > self.config.end_power:
            self.run_start = self.cycle.start
            self.run_significant = True
        else:
            self.run_start = None
            self.run_significant = False
        events.append(DetectorEvent(EventType.STARTED, t, None, self.cycle))

    def _reset_cycle_state(self) -> None:
        self.cycle = None
        self.run_start = None
        self.run_significant = False
        self.last_active = None

    def _finish(self, t: float, reason: FinishReason, events: list[DetectorEvent]) -> None:
        cycle = self.cycle
        assert cycle is not None
        if reason == FinishReason.UNAVAILABLE and self.unavailable_since is not None:
            end = min(self._active_end(t), self.unavailable_since)
        elif reason in (FinishReason.FORCED, FinishReason.PROGRAM_END):
            end = t
        else:
            end = self._active_end(t)
            if reason == FinishReason.SWITCHED_OFF and self.off_since is not None:
                end = min(end, self.off_since)
        cycle.end = max(end, cycle.start)
        cycle.finished_at = t
        cycle.reason = reason
        self._reset_cycle_state()

        if reason == FinishReason.UNAVAILABLE:
            self.phase = Phase.OFF
            events.append(DetectorEvent(EventType.ABORTED, t, reason, cycle))
            return
        if cycle.duration_s < self.config.min_cycle_s:
            cycle.reason = FinishReason.TOO_SHORT
            self.phase = Phase.OFF
            events.append(
                DetectorEvent(EventType.ABORTED, t, FinishReason.TOO_SHORT, cycle)
            )
            return
        self.last_cycle = cycle
        events.append(DetectorEvent(EventType.FINISHED, t, reason, cycle))
        if reason == FinishReason.SWITCHED_OFF:
            # Switched off at the machine: somebody is there, nothing waits.
            self.phase = Phase.OFF
            return
        self.phase = Phase.FINISHED
        self.finished_since = t
        if reason == FinishReason.PROGRAM_END:
            self.crease_active_at = t

    def _clear(self, t: float, reason: FinishReason, events: list[DetectorEvent]) -> None:
        if self.phase != Phase.FINISHED:
            return
        self.phase = Phase.OFF
        self.finished_since = None
        self.crease_active_at = None
        events.append(DetectorEvent(EventType.CLEARED, t, reason, self.last_cycle))

    # ---------------------------------------------------------- persistence

    _STATE_KEYS = (
        "last_ts",
        "power",
        "available",
        "unavailable_since",
        "cand_start",
        "cand_below_since",
        "run_start",
        "run_significant",
        "last_active",
        "off_since",
        "finished_since",
        "crease_active_at",
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize runtime state."""
        data: dict[str, Any] = {k: getattr(self, k) for k in self._STATE_KEYS}
        data["phase"] = str(self.phase)
        data["cycle"] = self.cycle.to_dict() if self.cycle else None
        data["last_cycle"] = self.last_cycle.to_dict() if self.last_cycle else None
        return data

    def restore(self, data: dict[str, Any]) -> None:
        """Restore runtime state from ``to_dict`` output."""
        for key in self._STATE_KEYS:
            if key in data:
                setattr(self, key, data[key])
        self.phase = Phase(data.get("phase", Phase.OFF))
        cyc = data.get("cycle")
        self.cycle = CycleRecord.from_dict(cyc) if cyc else None
        last = data.get("last_cycle")
        self.last_cycle = CycleRecord.from_dict(last) if last else None
        if self.phase == Phase.RUNNING and (self.cycle is None or self.last_active is None):
            self.phase = Phase.OFF
            self._reset_cycle_state()
