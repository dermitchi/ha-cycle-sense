"""Running binary sensor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .engine import Phase
from .entity import CycleSenseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    async_add_entities([RunningBinarySensor(entry.runtime_data, "running")])


class RunningBinarySensor(CycleSenseEntity, BinarySensorEntity):
    """On while a cycle runs."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        """Return true while running."""
        return self.coordinator.phase == Phase.RUNNING
