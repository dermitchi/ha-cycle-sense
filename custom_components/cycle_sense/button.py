"""Acknowledge button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CycleSenseConfigEntry
from .const import DOMAIN
from .entity import CycleSenseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CycleSenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    manager = entry.runtime_data
    async_add_entities(
        [AcknowledgeButton(manager, "acknowledge"), LearnLastButton(manager, "learn_last")]
    )


class AcknowledgeButton(CycleSenseEntity, ButtonEntity):
    """Marks a finished appliance as emptied."""

    async def async_press(self) -> None:
        """Handle the press."""
        self.coordinator.async_acknowledge()


class LearnLastButton(CycleSenseEntity, ButtonEntity):
    """Saves the last finished cycle under the entered program name."""

    async def async_press(self) -> None:
        """Handle the press."""
        try:
            await self.coordinator.async_learn_last()
        except ValueError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key=str(err)
            ) from err
