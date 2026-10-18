"""Program name used by the learn mode."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .entity import CycleSenseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the text entity."""
    async_add_entities([LearnNameText(entry.runtime_data, "learn_name")])


class LearnNameText(CycleSenseEntity, TextEntity):
    """Name of the program to record, e.g. "Cotton 40°"."""

    _attr_native_max = 60

    @property
    def native_value(self) -> str:
        """Return the name."""
        return self.coordinator.learn_name

    async def async_set_value(self, value: str) -> None:
        """Set the name."""
        self.coordinator.async_set_learn_name(value)
