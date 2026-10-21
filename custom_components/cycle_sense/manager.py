"""Glue between Home Assistant and the pure detection/matching engine."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from functools import partial
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.const import STATE_ON, UnitOfPower
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_APPLIANCE_TYPE,
    CONF_DOOR_SENSOR,
    CONF_POWER_SENSOR,
    DOMAIN,
    EVENT_ABORTED,
    EVENT_CLEARED,
    EVENT_FINISHED,
    EVENT_LEARNED,
    EVENT_STARTED,
    HISTORY_SIZE,
    MAX_PAUSE_S,
    NEAR_END_S,
    RESTORE_MAX_GAP_S,
    STORAGE_VERSION,
    TICK_SECONDS,
    TYPE_DEFAULTS,
    TYPE_OTHER,
)
from .engine import (
    CONFIDENT,
    SHOW_CONFIDENCE,
    CycleRecord,
    Detector,
    DetectorConfig,
    DetectorEvent,
    EventType,
    FinishReason,
    LearnResult,
    LoadEstimate,
    Match,
    Matcher,
    Phase,
    ProfileStore,
    Sample,
    blend_remaining,
    estimate_load,
    heat_wh,
    heating_end,
    predict_remaining,
    tail_bins,
)
from .engine.load import BASE_SHARE, DEFAULT_BASE_SHARE

if TYPE_CHECKING:
    from . import CycleSenseConfigEntry

_LOGGER = logging.getLogger(__name__)

_EVENT_NAMES = {
    EventType.STARTED: EVENT_STARTED,
    EventType.FINISHED: EVENT_FINISHED,
    EventType.ABORTED: EVENT_ABORTED,
    EventType.CLEARED: EVENT_CLEARED,
}
_LEARNABLE = {
    FinishReason.QUIET,
    FinishReason.PROGRAM_END,
    FinishReason.SWITCHED_OFF,
    FinishReason.FORCED,
}
_SAVE_DELAY_S = 60
_CREASE_WINDOW_S = 300
"""Movement within this time after finishing counts as anti-crease."""


def _parse_power(state: State | None) -> float | None:
    """Return watts, or None when the sensor has no usable value."""
    if state is None:
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None
    if state.attributes.get("unit_of_measurement") == UnitOfPower.KILO_WATT:
        value *= 1000
    return value


def _ts(value: float | None) -> datetime | None:
    return dt_util.utc_from_timestamp(value) if value is not None else None


def _sample(cycle: CycleRecord, source: str, minutes: float | None = None) -> Sample:
    if minutes is None or minutes * 60 >= cycle.duration_s:
        trace, duration, energy = cycle.trace(), cycle.duration_s, cycle.energy_wh
    else:
        # Cut off what followed the real program end (e.g. anti-crease).
        trace = cycle.trace()[: max(1, round(minutes * 60 / cycle.bin_s))]
        duration = minutes * 60
        energy = sum(trace) * cycle.bin_s / 3600
    return Sample(
        trace=trace,
        duration_s=duration,
        energy_wh=energy,
        recorded=cycle.start,
        source=source,
    )


class CycleManager(DataUpdateCoordinator[None]):
    """Feeds the detector, recognises programs, learns and persists."""

    config_entry: CycleSenseConfigEntry

    def __init__(self, hass: HomeAssistant, entry: CycleSenseConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title)
        appliance = entry.data.get(CONF_APPLIANCE_TYPE, TYPE_OTHER)
        self.config = DetectorConfig.from_dict({**TYPE_DEFAULTS[appliance], **entry.options})
        self.base_share = BASE_SHARE.get(appliance, DEFAULT_BASE_SHARE)
        self.detector = Detector(
            self.config, end_delay_fn=self._end_delay, program_end_fn=self._program_end
        )
        self.profiles = ProfileStore()
        self.matcher = Matcher(self.profiles, self.config.bin_s, self.config.end_power)
        self.power_entity: str = entry.data[CONF_POWER_SENSOR]
        self.door_entity: str | None = entry.data.get(CONF_DOOR_SENSOR)
        self.history: list[dict[str, Any]] = []
        self.cycle_count = 0
        self.learn_mode = False
        self.learn_name = ""
        self.load_next: float | None = None
        self.match: Match | None = None
        self._matched_start: float | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._lock = asyncio.Lock()
        self._unsubs: list[CALLBACK_TYPE] = []
        self._last_refresh = 0.0
        self._last_save = 0.0
        self._crease_shown = False

    @property
    def auto_name_fmt(self) -> str:
        """Name pattern for automatically grouped programs."""
        return "Programm {n}" if self.hass.config.language.startswith("de") else "Program {n}"

    # ------------------------------------------------------------ lifecycle

    async def async_start(self) -> None:
        """Restore state and start listening."""
        if data := await self._store.async_load():
            self.history = data.get("history", [])
            self.cycle_count = data.get("cycle_count", 0)
            self.learn_mode = data.get("learn_mode", False)
            self.learn_name = data.get("learn_name", "")
            self.load_next = data.get("load_next")
            self.profiles = await self.hass.async_add_executor_job(
                ProfileStore.from_dict, data.get("profiles")
            )
            self.matcher.store = self.profiles
            if runtime := data.get("detector"):
                self.detector.restore(runtime)
        self._handle(self.detector.handle_restore(time.time(), RESTORE_MAX_GAP_S))
        self._sync_matcher()

        self._unsubs.append(
            async_track_state_change_event(self.hass, self.power_entity, self._on_power)
        )
        if self.door_entity:
            self._unsubs.append(
                async_track_state_change_event(self.hass, self.door_entity, self._on_door)
            )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_tick, timedelta(seconds=TICK_SECONDS))
        )
        self._handle(
            self.detector.update(
                time.time(), _parse_power(self.hass.states.get(self.power_entity))
            )
        )

    async def async_stop(self) -> None:
        """Stop listening and save immediately."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data_to_save())

    # ------------------------------------------------------------ callbacks

    @callback
    def _on_power(self, event: Event[EventStateChangedData]) -> None:
        state = event.data["new_state"]
        ts = state.last_updated.timestamp() if state else time.time()
        before = self.power_w
        self._handle(self.detector.update(ts, _parse_power(state)))
        if self.power_w != before:
            self._refresh()

    @callback
    def _on_door(self, event: Event[EventStateChangedData]) -> None:
        state = event.data["new_state"]
        if state is not None and state.state == STATE_ON:
            self._handle(self.detector.door_opened(time.time()))

    @callback
    def _on_tick(self, _now: datetime) -> None:
        now = time.time()
        self._handle(self.detector.tick(now))
        if (
            self._sync_matcher()
            or (self.detector.phase == Phase.RUNNING and now - self._last_refresh >= 60)
            or self.anti_crease != self._crease_shown
        ):
            self._refresh()
        if self.detector.cycle is not None and now - self._last_save >= _SAVE_DELAY_S:
            self._save()

    # ----------------------------------------------------- user actions

    @callback
    def async_acknowledge(self) -> None:
        """User says the appliance was emptied."""
        self._handle(self.detector.acknowledge(time.time()))

    @callback
    def async_set_learn_mode(self, on: bool) -> None:
        """Switch the scan/learn mode."""
        self.learn_mode = on
        self._apply_pin()
        self._refresh()
        self._save()

    @callback
    def async_set_learn_name(self, name: str) -> None:
        """Set the program name used by the learn mode."""
        self.learn_name = name.strip()
        self._apply_pin()
        self._refresh()
        self._save()

    async def async_learn_last(
        self, name: str | None = None, minutes: float | None = None
    ) -> LearnResult:
        """Store the last finished cycle under ``name`` (default: learn name).

        ``minutes`` keeps only the start of the run, for when the cycle was
        reported late and the real program was shorter.
        """
        name = (name or self.learn_name).strip()
        cycle = self.detector.last_cycle
        if not name:
            raise ValueError("no_name")
        if cycle is None or not cycle.bins:
            raise ValueError("no_cycle")
        return await self._async_learn(_sample(cycle, "learn", minutes), name)

    @callback
    def async_set_load(self, load: float, target: str = "last") -> None:
        """Tell how full the drum was (last run) or will be (next run), 0..1."""
        if target == "next":
            self.load_next = load
        else:
            if not self.history:
                raise ValueError("no_cycle")
            last = self.history[0]
            last["load_set"] = load
            if (sample := self.profiles.find_sample(last["start"])) is not None:
                sample.load = load
        self._refresh()
        self._save()

    async def async_clear_unassigned(self) -> int:
        """Forget recorded runs that belong to no program."""
        async with self._lock:
            count = self.profiles.clear_unassigned()
        self._save()
        return count

    async def async_rename_program(self, old: str, new: str) -> bool:
        """Rename (or merge) a program."""
        async with self._lock:
            ok = await self.hass.async_add_executor_job(self.profiles.rename, old, new)
        self._after_profiles_changed()
        return ok

    async def async_delete_program(self, name: str) -> bool:
        """Delete a program."""
        ok = self.profiles.delete(name)
        self._after_profiles_changed()
        return ok

    async def async_import_history(self, days: int) -> dict[str, Any]:
        """Learn from cycles found in the recorder history."""
        from homeassistant.components.recorder import get_instance, history

        end = dt_util.utcnow()
        start = end - timedelta(days=days)
        states = await get_instance(self.hass).async_add_executor_job(
            partial(
                history.state_changes_during_period,
                self.hass,
                start,
                end,
                self.power_entity,
                no_attributes=False,
                include_start_time_state=True,
            )
        )
        detector = Detector(DetectorConfig.from_dict(vars(self.config)))
        cycles: list[CycleRecord] = []
        for state in states.get(self.power_entity, []):
            for event in detector.update(state.last_updated.timestamp(), _parse_power(state)):
                if event.type == EventType.FINISHED and event.cycle is not None:
                    cycles.append(event.cycle)
        known = [h["start"] for h in self.history] + [
            s.recorded for p in self.profiles.profiles for s in p.samples
        ] + [s.recorded for s in self.profiles.unassigned]
        new = [c for c in cycles if all(abs(c.start - k) > 600 for k in known)]

        results: list[LearnResult] = []
        async with self._lock:
            for cycle in new:
                results.append(
                    await self.hass.async_add_executor_job(
                        partial(
                            self.profiles.learn,
                            _sample(cycle, "import"),
                            auto_name_fmt=self.auto_name_fmt,
                        )
                    )
                )
        self._after_profiles_changed()
        return {
            "found": len(cycles),
            "imported": len(new),
            "assigned": sum(1 for r in results if r.profile),
            "programs": [p.summary() for p in self.profiles.profiles],
            "unassigned": len(self.profiles.unassigned),
        }

    # ------------------------------------------------------------ internals

    def _end_delay(self, quiet_since: float, now: float) -> float:
        self._sync_matcher()
        return self.matcher.end_delay(self.config.end_delay_s, NEAR_END_S, MAX_PAUSE_S)

    def _program_end(self, now: float) -> bool:
        if self.learn_mode:
            return False
        self._sync_matcher()
        return self.matcher.program_end_reached()

    @callback
    def _apply_pin(self) -> None:
        """While scanning a known program, show its remaining time directly."""
        name = self.learn_name if self.learn_mode else ""
        prof = self.profiles.get(name) if name else None
        self.matcher.pinned = prof.name if prof else None
        self.match = self.matcher.best() if self.detector.phase == Phase.RUNNING else None

    def _sync_matcher(self, *, force_reset: bool = False) -> bool:
        """Feed completed bins of the running cycle. True if anything changed.

        The matcher is bound to one cycle (by its start time) and resets
        itself when a new cycle shows up, so it can never mix two runs even
        when the detector starts and judges a cycle within one update.
        """
        cycle = self.detector.cycle
        if self.detector.phase != Phase.RUNNING or cycle is None:
            return False
        changed = False
        if force_reset or self._matched_start != cycle.start:
            self.matcher.reset()
            self._matched_start = cycle.start
            self._apply_pin()
            changed = True
        while self.matcher.n < len(cycle.bins):
            self.matcher.push(cycle.bins[self.matcher.n])
            changed = True
        if changed:
            self.match = self.matcher.best()
        return changed

    @callback
    def _after_profiles_changed(self) -> None:
        if not self._sync_matcher(force_reset=True):
            self._apply_pin()
        self._refresh()
        self._save()

    @callback
    def _handle(self, events: list[DetectorEvent]) -> None:
        for event in events:
            cycle = event.cycle
            data = self._event_data(event)
            if event.type == EventType.STARTED:
                self._sync_matcher()
            elif event.type == EventType.FINISHED and cycle is not None:
                # The detector has already left RUNNING here, so use the last
                # match directly instead of shown_match.
                match = (
                    self.match
                    if self.match and self.match.confidence >= SHOW_CONFIDENCE
                    else None
                )
                data["program"] = match.profile.name if match else None
                data["confidence"] = round(match.confidence * 100) if match else None
                self.cycle_count += 1
                self.history.insert(0, self._summary(cycle) | {"program": data["program"]})
                del self.history[HISTORY_SIZE:]
                self.match = None
                self._matched_start = None
                if self.load_next is not None:
                    self.history[0]["load_set"] = self.load_next
                self._estimate_last()
                if event.reason in _LEARNABLE:
                    name = self.learn_name if self.learn_mode else None
                    sample = _sample(cycle, "learn" if name else "auto")
                    sample.load = self.load_next
                    self.config_entry.async_create_background_task(
                        self.hass,
                        self._async_learn(sample, name, from_learn_mode=name is not None),
                        f"{DOMAIN}_learn",
                    )
                self.load_next = None
            _LOGGER.debug("%s: %s (%s)", self.name, event.type, event.reason)
            self.hass.bus.async_fire(_EVENT_NAMES[event.type], data)
        if events:
            self._refresh()
            self._save()

    async def _async_learn(
        self, sample: Sample, name: str | None, *, from_learn_mode: bool = False
    ) -> LearnResult:
        async with self._lock:
            result = await self.hass.async_add_executor_job(
                partial(self.profiles.learn, sample, name=name, auto_name_fmt=self.auto_name_fmt)
            )
        if from_learn_mode:
            # One scan per switch-on: the next run is recognised, not recorded.
            self.learn_mode = False
        if self.history and result.profile and abs(self.history[0]["start"] - sample.recorded) < 1:
            self.history[0]["program"] = result.profile
            self._estimate_last()
        if name or result.created:
            prof = self.profiles.get(result.profile) if result.profile else None
            count = len(prof.samples) if prof else 0
            title = self.config_entry.title
            if not self.hass.config.language.startswith("de"):
                text = (
                    f"**{title}**: saved “{result.profile}” ({count} recording(s))."
                    if name
                    else f"**{title}**: found a new program “{result.profile}” – feel free to rename it."
                )
            elif name:
                text = f"**{title}**: „{result.profile}“ gespeichert ({count} Aufnahme{'n' if count != 1 else ''})."
            else:
                text = f"**{title}**: neues Programm „{result.profile}“ erkannt – gern umbenennen."
            persistent_notification.async_create(
                self.hass,
                text,
                title="Cycle Sense",
                notification_id=f"{DOMAIN}_{self.config_entry.entry_id}_learned",
            )
        self.hass.bus.async_fire(
            EVENT_LEARNED,
            {
                "entry_id": self.config_entry.entry_id,
                "name": self.config_entry.title,
                "program": result.profile,
                "created": result.created,
            },
        )
        self._after_profiles_changed()
        return result

    def _estimate(
        self, program: str | None, heat: float, exclude: float | None = None
    ) -> LoadEstimate | None:
        """Load of a run of ``program`` with ``heat`` Wh, from calibrated runs."""
        prof = self.profiles.get(program) if program else None
        if prof is None:
            return None
        points = [
            (s.load, heat_wh(s.trace, self.config.bin_s))
            for s in prof.samples
            if s.load is not None and (exclude is None or abs(s.recorded - exclude) >= 1)
        ]
        return estimate_load(heat, points, self.base_share)

    @callback
    def _estimate_last(self) -> None:
        last = self.history[0]
        est = (
            self._estimate(last.get("program"), last["heat_wh"], last["start"])
            if "heat_wh" in last
            else None
        )
        last["load"] = round(est.load, 2) if est else None
        last["load_basis"] = est.basis if est else None

    @callback
    def _save(self) -> None:
        # async_delay_save restarts its timer on every call, so only call it
        # on real changes and on the per-minute tick, never per sample.
        self._last_save = time.time()
        self._store.async_delay_save(self._data_to_save, 1)

    @callback
    def _refresh(self) -> None:
        self._last_refresh = time.time()
        self._crease_shown = self.anti_crease
        self.async_update_listeners()

    def _summary(self, cycle: CycleRecord) -> dict[str, Any]:
        return {
            "start": cycle.start,
            "end": cycle.end,
            "finished_at": cycle.finished_at,
            "duration_min": round(cycle.duration_s / 60, 1),
            "energy_kwh": round(cycle.energy_wh / 1000, 3),
            "peak_w": round(cycle.peak_w),
            "reason": cycle.reason,
            "heat_wh": round(heat_wh(cycle.trace(), cycle.bin_s)),
        }

    def _event_data(self, event: DetectorEvent) -> dict[str, Any]:
        data: dict[str, Any] = {
            "entry_id": self.config_entry.entry_id,
            "name": self.config_entry.title,
            "reason": str(event.reason) if event.reason else None,
        }
        if (cycle := event.cycle) is not None:
            data |= {
                "start": dt_util.utc_from_timestamp(cycle.start).isoformat(),
                "end": _ts(cycle.end).isoformat() if cycle.end else None,
                "duration_min": round(cycle.duration_s / 60, 1),
                "energy_kwh": round(cycle.energy_wh / 1000, 3),
            }
        return data

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "detector": self.detector.to_dict(),
            "history": self.history,
            "cycle_count": self.cycle_count,
            "learn_mode": self.learn_mode,
            "learn_name": self.learn_name,
            "load_next": self.load_next,
            "profiles": self.profiles.to_dict(),
        }

    # ------------------------------------------------------ entity helpers

    @property
    def power_w(self) -> float | None:
        """Current power in watts (0 when switched off), None if unavailable."""
        if not self.detector.available or self.detector.power is None:
            return None
        return round(self.detector.power, 1)

    @property
    def phase(self) -> Phase:
        """Current phase."""
        return self.detector.phase

    @property
    def current_cycle(self) -> CycleRecord | None:
        """The running cycle, or None."""
        return self.detector.cycle if self.detector.phase == Phase.RUNNING else None

    @property
    def anti_crease(self) -> bool:
        """Finished, but the drum still moves now and then (anti-crease)."""
        det = self.detector
        if det.phase != Phase.FINISHED or det.motion_at is None:
            return False
        return time.time() - det.motion_at < _CREASE_WINDOW_S

    @property
    def load_info(self) -> dict[str, Any] | None:
        """How full the drum is (running, once heating is over) or was (last run)."""
        if (cycle := self.current_cycle) is not None:
            match = self.shown_match
            end = heating_end(match.profile.template) if match else None
            if match is None or end is None or match.position <= end + 1:
                return None
            if self.load_next is not None:
                return {"load": self.load_next, "source": "set", "program": match.profile.name}
            heat = heat_wh(cycle.bins, cycle.bin_s)
            est = self._estimate(match.profile.name, heat)
            if est is None:
                return None
            return {
                "load": est.load,
                "source": "live",
                "basis": est.basis,
                "calibrations": est.points,
                "heat_wh": round(heat),
                "program": match.profile.name,
            }
        last = self.last_cycle
        if not last:
            return None
        if last.get("load_set") is not None:
            return {"load": last["load_set"], "source": "set", "program": last.get("program")}
        if last.get("load") is None:
            return None
        return {
            "load": last["load"],
            "source": "estimate",
            "basis": last.get("load_basis"),
            "heat_wh": last.get("heat_wh"),
            "program": last.get("program"),
        }

    @property
    def last_cycle(self) -> dict[str, Any] | None:
        """Summary of the most recent finished cycle."""
        return self.history[0] if self.history else None

    @property
    def finished_since(self) -> datetime | None:
        """When the current finished state began."""
        return _ts(self.detector.finished_since)

    @property
    def quiet_for_s(self) -> float | None:
        """Seconds without significant activity while running."""
        since = self.detector.quiet_since(time.time())
        return None if since is None else round(time.time() - since)

    @property
    def shown_match(self) -> Match | None:
        """The current match if it is confident enough to show."""
        if self.match is None or self.current_cycle is None:
            return None
        return self.match if self.match.confidence >= SHOW_CONFIDENCE else None

    @property
    def remaining_s(self) -> float | None:
        """Estimated remaining seconds of the running cycle."""
        if self.shown_match is None or self.current_cycle is None:
            return None
        # Remaining is measured at the last completed bin; subtract the
        # part of the current bin that has already passed.
        cycle = self.current_cycle
        match = self.shown_match
        remaining = match.remaining_s
        if match.confidence >= CONFIDENT:
            # After heating, what is left (rinse, spin) takes about as long
            # as in the program's other runs, however full the drum is;
            # the shape match alone assumes the template's heating time.
            tail = predict_remaining(
                cycle.bins, [tail_bins(s.trace) for s in match.profile.samples], cycle.bin_s
            )
            if tail is not None:
                elapsed = len(cycle.bins) * cycle.bin_s
                remaining = blend_remaining(remaining, elapsed + tail, elapsed)
        into_bin = (time.time() - cycle.start) - len(cycle.bins) * cycle.bin_s
        return max(0.0, remaining - max(0.0, into_bin))
