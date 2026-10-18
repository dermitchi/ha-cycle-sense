"""Config and options flow for Cycle Sense."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    APPLIANCE_TYPES,
    CONF_APPLIANCE_TYPE,
    CONF_DOOR_SENSOR,
    CONF_POWER_SENSOR,
    DOMAIN,
    OPT_END_DELAY,
    OPT_END_POWER,
    OPT_FINISHED_TIMEOUT,
    OPT_MIN_CYCLE,
    OPT_SPIKE_MAX,
    OPT_START_POWER,
    TYPE_DEFAULTS,
    TYPE_WASHER,
)

# key -> (min, max, step, unit)
_OPTION_RANGES: dict[str, tuple[float, float, float, str]] = {
    OPT_START_POWER: (1, 3000, 1, "W"),
    OPT_END_POWER: (0.5, 500, 0.5, "W"),
    OPT_END_DELAY: (30, 7200, 10, "s"),
    OPT_SPIKE_MAX: (0, 900, 10, "s"),
    OPT_MIN_CYCLE: (0, 7200, 30, "s"),
    OPT_FINISHED_TIMEOUT: (0, 172800, 60, "s"),
}


class CycleSenseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add an appliance."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for name, power sensor and appliance type."""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_POWER_SENSOR])
            self._abort_if_unique_id_configured()
            data = {k: v for k, v in user_input.items() if k != CONF_NAME and v}
            return self.async_create_entry(title=user_input[CONF_NAME], data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class=SensorDeviceClass.POWER
                    )
                ),
                vol.Required(CONF_APPLIANCE_TYPE, default=TYPE_WASHER): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=APPLIANCE_TYPES,
                        translation_key=CONF_APPLIANCE_TYPE,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_DOOR_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> CycleSenseOptionsFlow:
        """Return the options flow."""
        return CycleSenseOptionsFlow()


class CycleSenseOptionsFlow(OptionsFlow):
    """Tune detection thresholds."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the thresholds, prefilled with current values."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        defaults = TYPE_DEFAULTS[self.config_entry.data.get(CONF_APPLIANCE_TYPE, TYPE_WASHER)]
        current = {**defaults, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(key, default=current[key]): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=lo, max=hi, step=step, unit_of_measurement=unit,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
                for key, (lo, hi, step, unit) in _OPTION_RANGES.items()
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
