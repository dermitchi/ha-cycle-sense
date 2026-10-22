"""Program name used by the learn mode."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .announcer import VARIABLES, Announcer
from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_ANNOUNCER
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
        appliances = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.data.get(CONF_ENTRY_TYPE) != ENTRY_ANNOUNCER
        ]
        async_add_entities(
            [ApplianceFinishedText(runtime, e.entry_id, e.title) for e in appliances]
            + [
                AnnouncerText(runtime, "text_reminder", "text_reminder"),
                AnnouncerText(runtime, "text_started", "text_started"),
                AnnouncerText(runtime, "text_dryer_free", "text_dryer_free"),
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
        """Set the name; a name starts recording the running/next cycle under it."""
        if value.strip():
            self.coordinator.async_choose_program(value)
        else:
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


class ApplianceFinishedText(CycleSenseEntity[Announcer], TextEntity):
    """Finished text of one appliance; placeholders like {geraet} {programm} {dauer}."""

    _attr_native_max = 255

    def __init__(self, coordinator: Announcer, appliance_id: str, appliance_name: str) -> None:
        """Initialize."""
        super().__init__(coordinator, "text_finished_device")
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_text_finished_{appliance_id}"
        self._attr_translation_placeholders = {"device": appliance_name}
        self._appliance_id = appliance_id

    @property
    def native_value(self) -> str:
        """Return the template."""
        return self.coordinator.finished_text(self._appliance_id)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """List the available placeholders."""
        return {"variables": " ".join("{" + v + "}" for v in VARIABLES)}

    async def async_set_value(self, value: str) -> None:
        """Set the template."""
        self.coordinator.async_set_finished_text(self._appliance_id, value.strip())
