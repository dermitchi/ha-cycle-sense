"""Load and program of the running/next cycle."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .entity import CycleSenseEntity
from .manager import CycleManager

NONE = "none"
LOADS = {"low": 0.33, "half": 0.5, "three_quarter": 0.75, "full": 1.0}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select (appliances only)."""
    if isinstance(entry.runtime_data, CycleManager):
        async_add_entities(
            [
                NextLoadSelect(entry.runtime_data, "load_next"),
                ProgramSelect(entry.runtime_data, "program_next"),
            ]
        )


class NextLoadSelect(CycleSenseEntity[CycleManager], SelectEntity):
    """Load of the next cycle; resets once that cycle has finished."""

    _attr_options = [NONE, *LOADS]

    @property
    def current_option(self) -> str:
        """Closest option to the load set for the next cycle."""
        load = self.coordinator.load_next
        if load is None:
            return NONE
        return min(LOADS, key=lambda k: abs(LOADS[k] - load))

    async def async_select_option(self, option: str) -> None:
        """Set or clear the load of the next cycle."""
        if option == NONE:
            self.coordinator.async_set_load(0, "clear")
        else:
            self.coordinator.async_set_load(LOADS[option], "next")


AUTO = "auto"


class ProgramSelect(CycleSenseEntity[CycleManager], SelectEntity):
    """Program of the running/next cycle, picked from the learned ones.

    A new program is started by typing its name into the learn-name text.
    """

    @property
    def options(self) -> list[str]:
        """Automatic plus every learned program (and a new one being learned)."""
        names = self.coordinator.program_names
        if self.coordinator.learning_new_program:
            names.append(self.coordinator.learn_name)
        return [AUTO, *names]

    @property
    def current_option(self) -> str:
        """The chosen program, or automatic recognition."""
        if self.coordinator.learn_mode and self.coordinator.learn_name:
            return self.coordinator.learn_name
        return AUTO

    async def async_select_option(self, option: str) -> None:
        """Choose a program or go back to automatic recognition."""
        self.coordinator.async_choose_program(None if option == AUTO else option)
