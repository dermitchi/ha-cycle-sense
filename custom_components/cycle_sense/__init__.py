"""Cycle Sense: reliable cycle detection and program recognition for appliances."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .manager import CycleManager

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type CycleSenseConfigEntry = ConfigEntry[CycleManager]

ATTR_ENTRY = "config_entry_id"
_ENTRY = vol.Required(ATTR_ENTRY)
_NAME = vol.All(cv.string, vol.Length(min=1, max=60))

SCHEMAS = {
    "learn_last_cycle": vol.Schema({_ENTRY: cv.string, vol.Required("program"): _NAME}),
    "rename_program": vol.Schema(
        {_ENTRY: cv.string, vol.Required("program"): _NAME, vol.Required("new_name"): _NAME}
    ),
    "delete_program": vol.Schema({_ENTRY: cv.string, vol.Required("program"): _NAME}),
    "import_history": vol.Schema(
        {_ENTRY: cv.string, vol.Optional("days", default=10): vol.All(int, vol.Range(1, 60))}
    ),
}


def _manager(hass: HomeAssistant, call: ServiceCall) -> CycleManager:
    entry = hass.config_entries.async_get_entry(call.data[ATTR_ENTRY])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="bad_entry")
    return entry.runtime_data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services."""

    async def learn_last_cycle(call: ServiceCall) -> ServiceResponse:
        try:
            result = await _manager(hass, call).async_learn_last(call.data["program"])
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=str(err)
            ) from err
        return {"program": result.profile, "created": result.created}

    async def rename_program(call: ServiceCall) -> None:
        if not await _manager(hass, call).async_rename_program(
            call.data["program"], call.data["new_name"]
        ):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_program")

    async def delete_program(call: ServiceCall) -> None:
        if not await _manager(hass, call).async_delete_program(call.data["program"]):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_program")

    async def import_history(call: ServiceCall) -> ServiceResponse:
        return await _manager(hass, call).async_import_history(call.data["days"])

    hass.services.async_register(
        DOMAIN, "learn_last_cycle", learn_last_cycle, SCHEMAS["learn_last_cycle"],
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, "rename_program", rename_program, SCHEMAS["rename_program"])
    hass.services.async_register(DOMAIN, "delete_program", delete_program, SCHEMAS["delete_program"])
    hass.services.async_register(
        DOMAIN, "import_history", import_history, SCHEMAS["import_history"],
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


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
