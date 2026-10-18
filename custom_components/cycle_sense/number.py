"""Announcement volume."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .announcer import Announcer
from .entity import CycleSenseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the volume number (announcer only)."""
    if isinstance(entry.runtime_data, Announcer):
        async_add_entities([VolumeNumber(entry.runtime_data, "volume")])


class VolumeNumber(CycleSenseEntity[Announcer], NumberEntity):
    """Volume used for announcements; restored afterwards."""

    _attr_native_min_value = 5
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float:
        """Return the volume."""
        return self.coordinator.volume

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume."""
        self.coordinator.async_set(volume=value)
