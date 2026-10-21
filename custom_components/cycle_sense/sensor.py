"""Sensors for Cycle Sense."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import CycleSenseConfigEntry
from .engine import Phase
from .engine.load import level
from .announcer import Announcer
from .entity import CycleSenseEntity
from .manager import CycleManager


def _elapsed(m: CycleManager) -> float | None:
    cycle = m.current_cycle
    return None if cycle is None else round((time.time() - cycle.start) / 60)


def _energy(m: CycleManager) -> float | None:
    if (cycle := m.current_cycle) is not None:
        return round(cycle.energy_wh / 1000, 3)
    return m.last_cycle["energy_kwh"] if m.last_cycle else None


def _last_end(m: CycleManager) -> datetime | None:
    last = m.last_cycle
    return dt_util.utc_from_timestamp(last["end"]) if last and last.get("end") else None


def _program(m: CycleManager) -> str | None:
    return m.shown_match.profile.name if m.shown_match else None


def _program_attrs(m: CycleManager) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "programs": [p.summary() for p in m.profiles.profiles],
        "unassigned_cycles": len(m.profiles.unassigned),
    }
    if m.match and m.current_cycle:
        attrs["confidence"] = round(m.match.confidence * 100)
        attrs["best_guess"] = m.match.profile.name
        attrs["candidates"] = {
            prof.name: round(prob * 100) for prof, _, prob in m.matcher.candidates()[:3]
        }
    return attrs


def _remaining(m: CycleManager) -> float | None:
    rem = m.remaining_s
    return None if rem is None else round(rem / 60)


def _finish_time(m: CycleManager) -> datetime | None:
    rem = m.remaining_s
    if rem is None:
        return None
    # Round to the minute so the state does not change every tick.
    return dt_util.utc_from_timestamp(round((time.time() + rem) / 60) * 60)


def _progress(m: CycleManager) -> int | None:
    return round(m.shown_match.progress * 100) if m.shown_match else None


def _status_attrs(m: CycleManager) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    if (cycle := m.current_cycle) is not None:
        attrs["started"] = dt_util.utc_from_timestamp(cycle.start).isoformat()
        attrs["quiet_for_s"] = m.quiet_for_s
    if m.phase == Phase.FINISHED and m.finished_since:
        attrs["finished_since"] = m.finished_since.isoformat()
    return attrs


def _last_attrs(m: CycleManager) -> dict[str, Any]:
    last = m.last_cycle
    if not last:
        return {}
    return {
        "start": dt_util.utc_from_timestamp(last["start"]).isoformat(),
        "duration_min": last["duration_min"],
        "energy_kwh": last["energy_kwh"],
        "peak_w": last["peak_w"],
        "reason": last["reason"],
        "program": last.get("program"),
    }


def _load(m: CycleManager) -> int | None:
    info = m.load_info
    return None if info is None else round(info["load"] * 100)


def _load_attrs(m: CycleManager) -> dict[str, Any]:
    info = m.load_info
    if info is None:
        return {"next_set": round(m.load_next * 100) if m.load_next is not None else None}
    return {k: v for k, v in info.items() if k != "load"} | {
        "level": level(info["load"]),
        "next_set": round(m.load_next * 100) if m.load_next is not None else None,
    }


@dataclass(frozen=True, kw_only=True)
class CycleSensorDescription(SensorEntityDescription):
    """Describes a Cycle Sense sensor."""

    value_fn: Callable[[CycleManager], Any]
    attrs_fn: Callable[[CycleManager], dict[str, Any]] | None = None


SENSORS: tuple[CycleSensorDescription, ...] = (
    CycleSensorDescription(
        key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda m: m.power_w,
    ),
    CycleSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[p.value for p in Phase],
        value_fn=lambda m: m.phase.value,
        attrs_fn=_status_attrs,
    ),
    CycleSensorDescription(
        key="program",
        value_fn=_program,
        attrs_fn=_program_attrs,
    ),
    CycleSensorDescription(
        key="remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_remaining,
    ),
    CycleSensorDescription(
        key="finish_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_finish_time,
    ),
    CycleSensorDescription(
        key="progress",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_progress,
    ),
    CycleSensorDescription(
        key="elapsed",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_elapsed,
    ),
    CycleSensorDescription(
        key="cycle_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_energy,
    ),
    CycleSensorDescription(
        key="last_cycle",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_end,
        attrs_fn=_last_attrs,
    ),
    CycleSensorDescription(
        key="load",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_load,
        attrs_fn=_load_attrs,
    ),
    CycleSensorDescription(
        key="cycle_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda m: m.cycle_count,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    runtime = entry.runtime_data
    if isinstance(runtime, Announcer):
        async_add_entities([LastAnnouncementSensor(runtime, "last_announcement")])
        return
    async_add_entities(CycleSensor(runtime, d) for d in SENSORS)


class CycleSensor(CycleSenseEntity[CycleManager], SensorEntity):
    """Generic Cycle Sense sensor."""

    entity_description: CycleSensorDescription

    def __init__(self, manager: CycleManager, description: CycleSensorDescription) -> None:
        """Initialize."""
        super().__init__(manager, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator) if fn else None


class LastAnnouncementSensor(CycleSenseEntity[Announcer], SensorEntity):
    """When the last announcement was spoken, with its text."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the last announcement."""
        return self.coordinator.last_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return text and last skip reason."""
        return {"text": self.coordinator.last_text, "last_skipped": self.coordinator.last_skipped}
