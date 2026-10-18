"""Base entity for Cycle Sense."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_APPLIANCE_TYPE, DOMAIN
from .manager import CycleManager


class CycleSenseEntity(CoordinatorEntity[CycleManager]):
    """Entity bound to one appliance."""

    _attr_has_entity_name = True

    def __init__(self, manager: CycleManager, key: str) -> None:
        """Initialize."""
        super().__init__(manager)
        entry = manager.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Cycle Sense",
            model=entry.data.get(CONF_APPLIANCE_TYPE),
        )
