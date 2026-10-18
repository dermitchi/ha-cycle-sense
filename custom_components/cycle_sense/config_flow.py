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
    CHIMES,
    CONF_APPLIANCE_TYPE,
    CONF_CHIME,
    CONF_DOOR_SENSOR,
    CONF_ENTRY_TYPE,
    CONF_MEDIA_PLAYERS,
    CONF_PERSONS,
    CONF_POWER_SENSOR,
    CONF_QUIET_END,
    CONF_REMINDERS,
    CONF_QUIET_START,
    CONF_TTS,
    DEFAULT_CHIME,
    DEFAULT_QUIET_END,
    DEFAULT_REMINDERS,
    DEFAULT_QUIET_START,
    DOMAIN,
    ENTRY_ANNOUNCER,
    ENTRY_APPLIANCE,
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

ACTION_RENAME = "rename"
ACTION_DELETE = "delete"


def _announcer_schema(defaults: dict[str, Any]) -> vol.Schema:
    def sv(key: str, fallback: Any = None) -> dict[str, Any]:
        value = defaults.get(key, fallback)
        return {"suggested_value": value} if value is not None else {}

    return vol.Schema(
        {
            vol.Required(CONF_MEDIA_PLAYERS, description=sv(CONF_MEDIA_PLAYERS)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=True)
            ),
            vol.Required(CONF_TTS, description=sv(CONF_TTS)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="tts")
            ),
            vol.Optional(CONF_CHIME, description=sv(CONF_CHIME, DEFAULT_CHIME)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=CHIMES, translation_key=CONF_CHIME, custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_QUIET_START, description=sv(CONF_QUIET_START, DEFAULT_QUIET_START)
            ): selector.TimeSelector(),
            vol.Optional(
                CONF_QUIET_END, description=sv(CONF_QUIET_END, DEFAULT_QUIET_END)
            ): selector.TimeSelector(),
            vol.Optional(
                CONF_REMINDERS, description=sv(CONF_REMINDERS, DEFAULT_REMINDERS)
            ): selector.TextSelector(),
            vol.Optional(CONF_PERSONS, description=sv(CONF_PERSONS)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="person", multiple=True)
            ),
        }
    )


class CycleSenseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add an appliance or the announcer."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose what to add."""
        return self.async_show_menu(step_id="user", menu_options=[ENTRY_APPLIANCE, ENTRY_ANNOUNCER])

    async def async_step_appliance(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for name, power sensor and appliance type."""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_POWER_SENSOR])
            self._abort_if_unique_id_configured()
            data = {k: v for k, v in user_input.items() if k != CONF_NAME and v}
            data[CONF_ENTRY_TYPE] = ENTRY_APPLIANCE
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
        return self.async_show_form(step_id="appliance", data_schema=schema)

    async def async_step_announcer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up spoken announcements (one per installation)."""
        await self.async_set_unique_id(ENTRY_ANNOUNCER)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(
                title=user_input.pop(CONF_NAME),
                data={CONF_ENTRY_TYPE: ENTRY_ANNOUNCER, **user_input},
            )
        schema = vol.Schema({vol.Required(CONF_NAME, default="Durchsagen"): selector.TextSelector()})
        schema = schema.extend(_announcer_schema({}).schema)
        return self.async_show_form(step_id="announcer", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> CycleSenseOptionsFlow:
        """Return the options flow."""
        return CycleSenseOptionsFlow()


class CycleSenseOptionsFlow(OptionsFlow):
    """Tune detection, manage programs, or configure announcements."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Entry point."""
        if self.config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_ANNOUNCER:
            return await self.async_step_announcer()
        return self.async_show_menu(step_id="init", menu_options=["settings", "programs"])

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Detection thresholds, prefilled with current values."""
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
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_programs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Rename or delete learned programs."""
        manager = self.config_entry.runtime_data
        names = manager.profiles.names()
        if not names:
            return self.async_abort(reason="no_programs")

        errors: dict[str, str] = {}
        if user_input is not None:
            program = user_input["program"]
            if user_input["action"] == ACTION_DELETE:
                await manager.async_delete_program(program)
                return self.async_create_entry(data=dict(self.config_entry.options))
            new_name = (user_input.get("new_name") or "").strip()
            if not new_name:
                errors["new_name"] = "name_required"
            else:
                await manager.async_rename_program(program, new_name)
                return self.async_create_entry(data=dict(self.config_entry.options))

        lines = [
            f"• {p['name']}: {p['samples']}× · ~{p['duration_min']} min · {p['energy_kwh']} kWh"
            for p in (prof.summary() for prof in manager.profiles.profiles)
        ]
        schema = vol.Schema(
            {
                vol.Required("program", default=names[0]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=names, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Required("action", default=ACTION_RENAME): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[ACTION_RENAME, ACTION_DELETE], translation_key="program_action"
                    )
                ),
                vol.Optional("new_name"): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="programs",
            data_schema=schema,
            errors=errors,
            description_placeholders={"programs": "\n".join(lines)},
        )

    async def async_step_announcer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Speakers, voice, quiet hours and presence."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="announcer", data_schema=_announcer_schema(current))
