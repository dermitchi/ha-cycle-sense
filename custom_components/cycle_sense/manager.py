"""Glue between Home Assistant and the pure detector."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_ON, UnitOfPower
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
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
    EVENT_STARTED,
    HISTORY_SIZE,
    RESTORE_MAX_GAP_S,
    STORAGE_VERSION,
    TICK_SECONDS,
    TYPE_DEFAULTS,
    TYPE_OTHER,
)
from .engine import CycleRecord, Detector, DetectorConfig, DetectorEvent, EventType, Phase

if TYPE_CHECKING:
    from . import CycleSenseConfigEntry

_LOGGER = logging.getLogger(__name__)

_EVENT_NAMES = {
    EventType.STARTED: EVENT_STARTED,
    EventType.FINISHED: EVENT_FINISHED,
    EventType.ABORTED: EVENT_ABORTED,
    EventType.CLEARED: EVENT_CLEARED,
}
_SAVE_DELAY_S = 60


def _parse_power(state: State | None) -> float | None:
    """Return watts, or None when the sensor has no usable value."""
    if state is None:
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None
    unit = state.attributes.get("unit_of_measurement")
    if unit == UnitOfPower.KILO_WATT:
        value *= 1000
    return value


def _ts(value: float | None) -> datetime | None:
    return dt_util.utc_from_timestamp(value) if value is not None else None


class CycleManager(DataUpdateCoordinator[None]):
    """Feeds the detector, persists its state and publishes changes."""

    config_entry: CycleSenseConfigEntry

    def __init__(self, hass: HomeAssistant, entry: CycleSenseConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title)
        appliance = entry.data.get(CONF_APPLIANCE_TYPE, TYPE_OTHER)
        settings = {**TYPE_DEFAULTS[appliance], **entry.options}
        self.detector = Detector(DetectorConfig.from_dict(settings))
        self.power_entity: str = entry.data[CONF_POWER_SENSOR]
        self.door_entity: str | None = entry.data.get(CONF_DOOR_SENSOR)
        self.history: list[dict[str, Any]] = []
        self.cycle_count = 0
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._unsubs: list[CALLBACK_TYPE] = []
        self._last_refresh = 0.0
        self._last_save = 0.0

    # ------------------------------------------------------------ lifecycle

    async def async_start(self) -> None:
        """Restore state and start listening."""
        if data := await self._store.async_load():
            self.history = data.get("history", [])
            self.cycle_count = data.get("cycle_count", 0)
            if runtime := data.get("detector"):
                self.detector.restore(runtime)
        self._handle(self.detector.handle_restore(time.time(), RESTORE_MAX_GAP_S))

        self._unsubs.append(
            async_track_state_change_event(self.hass, self.power_entity, self._on_power)
        )
        if self.door_entity:
            self._unsubs.append(
                async_track_state_change_event(self.hass, self.door_entity, self._on_door)
            )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._on_tick, timedelta(seconds=TICK_SECONDS)
            )
        )
        self._handle(
            self.detector.update(time.time(), _parse_power(self.hass.states.get(self.power_entity)))
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
        self._handle(self.detector.update(ts, _parse_power(state)))

    @callback
    def _on_door(self, event: Event[EventStateChangedData]) -> None:
        state = event.data["new_state"]
        if state is not None and state.state == STATE_ON:
            self._handle(self.detector.door_opened(time.time()))

    @callback
    def _on_tick(self, _now: datetime) -> None:
        now = time.time()
        self._handle(self.detector.tick(now))
        # Keep the elapsed time fresh once a minute while running.
        if self.detector.phase == Phase.RUNNING and now - self._last_refresh >= 60:
            self._refresh()
        if self.detector.cycle is not None and now - self._last_save >= _SAVE_DELAY_S:
            self._save()

    @callback
    def async_acknowledge(self) -> None:
        """User says the appliance was emptied."""
        self._handle(self.detector.acknowledge(time.time()))

    # ------------------------------------------------------------ internals

    @callback
    def _handle(self, events: list[DetectorEvent]) -> None:
        for event in events:
            cycle = event.cycle
            if event.type == EventType.FINISHED and cycle is not None:
                self.cycle_count += 1
                self.history.insert(0, self._summary(cycle))
                del self.history[HISTORY_SIZE:]
            _LOGGER.debug("%s: %s (%s)", self.name, event.type, event.reason)
            self.hass.bus.async_fire(_EVENT_NAMES[event.type], self._event_data(event))
        if events:
            self._refresh()
            self._save()

    @callback
    def _save(self) -> None:
        # async_delay_save restarts its timer on every call, so only call it
        # on real changes and on the per-minute tick, never per sample.
        self._last_save = time.time()
        self._store.async_delay_save(self._data_to_save, 1)

    @callback
    def _refresh(self) -> None:
        self._last_refresh = time.time()
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
        }

    # ------------------------------------------------------ entity helpers

    @property
    def phase(self) -> Phase:
        """Current phase."""
        return self.detector.phase

    @property
    def current_cycle(self) -> CycleRecord | None:
        """The running cycle, or None."""
        return self.detector.cycle if self.detector.phase == Phase.RUNNING else None

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
