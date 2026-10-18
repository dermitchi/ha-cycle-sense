"""Learn (scan) mode switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .entity import CycleSenseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch."""
    async_add_entities([LearnModeSwitch(entry.runtime_data, "learn_mode")])


class LearnModeSwitch(CycleSenseEntity, SwitchEntity):
    """While on, the current/next cycle is saved under the program name."""

    @property
    def is_on(self) -> bool:
        """Return the learn mode."""
        return self.coordinator.learn_mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Show which program will be recorded."""
        return {"program_name": self.coordinator.learn_name or None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start scanning."""
        self.coordinator.async_set_learn_mode(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop scanning."""
        self.coordinator.async_set_learn_mode(False)
