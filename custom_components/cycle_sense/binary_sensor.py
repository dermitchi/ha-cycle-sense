"""Running and anti-crease binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .engine import Phase
from .entity import CycleSenseEntity
from .manager import CycleManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    async_add_entities(
        [
            RunningBinarySensor(entry.runtime_data, "running"),
            AntiCreaseBinarySensor(entry.runtime_data, "anti_crease"),
        ]
    )


class RunningBinarySensor(CycleSenseEntity[CycleManager], BinarySensorEntity):
    """On while a cycle runs."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        """Return true while running."""
        return self.coordinator.phase == Phase.RUNNING


class AntiCreaseBinarySensor(CycleSenseEntity[CycleManager], BinarySensorEntity):
    """On while the finished appliance still turns the drum (anti-crease)."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        """Return true during anti-crease."""
        return self.coordinator.anti_crease
