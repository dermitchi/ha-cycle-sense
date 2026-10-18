"""Acknowledge button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .entity import CycleSenseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    async_add_entities([AcknowledgeButton(entry.runtime_data, "acknowledge")])


class AcknowledgeButton(CycleSenseEntity, ButtonEntity):
    """Marks a finished appliance as emptied."""

    async def async_press(self) -> None:
        """Handle the press."""
        self.coordinator.async_acknowledge()
