"""Cycle Sense: reliable start/finish detection for washers, dryers and co."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .manager import CycleManager

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]

type CycleSenseConfigEntry = ConfigEntry[CycleManager]


async def async_setup_entry(hass: HomeAssistant, entry: CycleSenseConfigEntry) -> bool:
    """Set up an appliance from a config entry."""
    manager = CycleManager(hass, entry)
    await manager.async_start()
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CycleSenseConfigEntry) -> bool:
    """Unload a config entry and persist the running state."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: CycleSenseConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
