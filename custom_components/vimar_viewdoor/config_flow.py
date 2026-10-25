"""Manual LAN credential import; never asks for a MyVimar account password."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from .const import DOMAIN
from .protocol import validate_credentials


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GateOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                validate_credentials(**user_input)
            except (ValueError, TypeError):
                errors["base"] = "invalid_credentials"
            else:
                await self.async_set_unique_id(user_input["device_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Vimar View Door", data=user_input)
        password = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("host"): str,
                    vol.Required("device_id"): str,
                    vol.Required("stream_key"): password,
                    vol.Required("auth_code"): password,
                }
            ),
            errors=errors,
        )


class GateOptionsFlow(config_entries.OptionsFlow):
    """Map output labels without sending any actuation or credential probe."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input["pedestrian_output"] == user_input["driveway_output"]:
                errors["base"] = "duplicate_output"
            else:
                return self.async_create_entry(title="", data=user_input)
        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "pedestrian_output", default=current.get("pedestrian_output", 1)
                    ): vol.In([1, 2]),
                    vol.Required(
                        "driveway_output", default=current.get("driveway_output", 2)
                    ): vol.In([1, 2]),
                    vol.Optional(
                        "unlock_password", default=current.get("unlock_password", "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Required(
                        "unlock_password_mode",
                        default=current.get("unlock_password_mode", "sha256"),
                    ): vol.In(["sha256", "plain"]),
                }
            ),
            errors=errors,
        )
