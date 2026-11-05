"""Config and options flow for Merged Calendar."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import CONF_CALENDARS, DEFAULT_NAME, DOMAIN


def _calendar_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="calendar", multiple=True))


def _validate(hass, calendars: list[str]) -> dict[str, str]:
    if not calendars:
        return {CONF_CALENDARS: "no_calendars"}
    reg = er.async_get(hass)
    for entity_id in calendars:
        ent = reg.async_get(entity_id)
        if ent and ent.platform == DOMAIN:
            return {CONF_CALENDARS: "no_nesting"}
    return {}


class MergedCalendarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a merged calendar."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(self.hass, user_input[CONF_CALENDARS])
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_NAME: user_input[CONF_NAME]},
                    options={CONF_CALENDARS: user_input[CONF_CALENDARS]},
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_CALENDARS): _calendar_selector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MergedCalendarOptionsFlow()


class MergedCalendarOptionsFlow(OptionsFlow):
    """Change which calendars are merged."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(self.hass, user_input[CONF_CALENDARS])
            if not errors:
                return self.async_create_entry(data={CONF_CALENDARS: user_input[CONF_CALENDARS]})
        current = self.config_entry.options.get(CONF_CALENDARS, [])
        schema = vol.Schema({vol.Required(CONF_CALENDARS, default=current): _calendar_selector()})
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
