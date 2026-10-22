"""Learn (scan) mode switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .announcer import Announcer
from .entity import CycleSenseEntity
from .manager import CycleManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch."""
    runtime = entry.runtime_data
    if isinstance(runtime, Announcer):
        async_add_entities([AnnouncerSwitch(runtime, "announcements")])
    else:
        async_add_entities([LearnModeSwitch(runtime, "learn_mode")])


class LearnModeSwitch(CycleSenseEntity[CycleManager], SwitchEntity):
    """While on, the current/next cycle is saved under the program name."""

    @property
    def is_on(self) -> bool:
        """Return the learn mode."""
        return self.coordinator.learn_mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Show which program will be recorded."""
        return {
            "program_name": self.coordinator.learn_name or None,
            "new_program": self.coordinator.learning_new_program,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start scanning."""
        self.coordinator.async_set_learn_mode(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop scanning."""
        self.coordinator.async_set_learn_mode(False)


class AnnouncerSwitch(CycleSenseEntity[Announcer], SwitchEntity):
    """Turns spoken announcements on or off."""

    @property
    def is_on(self) -> bool:
        """Return whether announcements are enabled."""
        return self.coordinator.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable announcements."""
        self.coordinator.async_set(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable announcements."""
        self.coordinator.async_set(enabled=False)
