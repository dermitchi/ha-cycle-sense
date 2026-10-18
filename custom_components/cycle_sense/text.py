"""Program name used by the learn mode."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .announcer import VARIABLES, Announcer
from .entity import CycleSenseEntity
from .manager import CycleManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the text entity."""
    runtime = entry.runtime_data
    if isinstance(runtime, Announcer):
        async_add_entities(
            [
                AnnouncerText(runtime, "text_finished", "text_finished"),
                AnnouncerText(runtime, "text_started", "text_started"),
            ]
        )
    else:
        async_add_entities([LearnNameText(runtime, "learn_name")])


class LearnNameText(CycleSenseEntity[CycleManager], TextEntity):
    """Name of the program to record, e.g. "Cotton 40°"."""

    _attr_native_max = 60

    @property
    def native_value(self) -> str:
        """Return the name."""
        return self.coordinator.learn_name

    async def async_set_value(self, value: str) -> None:
        """Set the name."""
        self.coordinator.async_set_learn_name(value)


class AnnouncerText(CycleSenseEntity[Announcer], TextEntity):
    """Announcement template; placeholders: {geraet} {programm} {dauer} {energie} {uhrzeit}."""

    _attr_native_max = 255

    def __init__(self, coordinator: Announcer, key: str, attr: str) -> None:
        """Initialize."""
        super().__init__(coordinator, key)
        self._field = attr

    @property
    def native_value(self) -> str:
        """Return the template."""
        return getattr(self.coordinator, self._field)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """List the available placeholders."""
        return {"variables": " ".join("{" + v + "}" for v in VARIABLES)}

    async def async_set_value(self, value: str) -> None:
        """Set the template."""
        self.coordinator.async_set(**{self._field: value.strip()})
