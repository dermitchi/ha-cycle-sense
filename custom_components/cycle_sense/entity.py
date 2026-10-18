"""Base entity for Cycle Sense."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import CONF_APPLIANCE_TYPE, CONF_ENTRY_TYPE, DOMAIN, ENTRY_ANNOUNCER


class CycleSenseEntity[_C: DataUpdateCoordinator[Any]](CoordinatorEntity[_C]):
    """Entity bound to one Cycle Sense device (appliance or announcer)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: _C, key: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        announcer = entry.data.get(CONF_ENTRY_TYPE) == ENTRY_ANNOUNCER
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Cycle Sense",
            model="Announcer" if announcer else entry.data.get(CONF_APPLIANCE_TYPE),
        )
