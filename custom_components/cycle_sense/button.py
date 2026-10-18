"""Acknowledge button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .announcer import Announcer, render
from .const import DOMAIN
from .entity import CycleSenseEntity
from .manager import CycleManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    runtime = entry.runtime_data
    if isinstance(runtime, Announcer):
        async_add_entities([TestAnnouncementButton(runtime, "test_announcement")])
        return
    async_add_entities(
        [AcknowledgeButton(runtime, "acknowledge"), LearnLastButton(runtime, "learn_last")]
    )


class AcknowledgeButton(CycleSenseEntity[CycleManager], ButtonEntity):
    """Marks a finished appliance as emptied."""

    async def async_press(self) -> None:
        """Handle the press."""
        self.coordinator.async_acknowledge()


class LearnLastButton(CycleSenseEntity[CycleManager], ButtonEntity):
    """Saves the last finished cycle under the entered program name."""

    async def async_press(self) -> None:
        """Handle the press."""
        try:
            await self.coordinator.async_learn_last()
        except ValueError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key=str(err)
            ) from err


class TestAnnouncementButton(CycleSenseEntity[Announcer], ButtonEntity):
    """Speaks the finished text with example values (ignores quiet hours)."""

    async def async_press(self) -> None:
        """Handle the press."""
        ann = self.coordinator
        text = render(
            ann.finished_text(next(iter(ann.texts_finished), None)),
            ann.values({"name": "Waschmaschine", "program": "Baumwolle 40°", "duration_min": 85, "energy_kwh": 0.54}),
        )
        if not await ann.async_announce(text, force=True):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="announce_failed")
