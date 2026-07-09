"""Config flow for Raylogic H81 - HA UI se sirf IP aur Start Address maangta hai.

Home Assistant mein: Settings -> Devices & Services -> Add Integration ->
"Raylogic H81" search karo. Form mein 2 hi fields honge: IP address aur
Start Address (Raylogic GO app ke Device Info screen se, jaise "0x0101").
Submit karte hi panel ke 8 channels khud calculate ho jaate hain aur light
entities ban jaati hain.

Agar zyada panels add karne hon, to "Add Integration" dubara use karo -
har baar ek naya panel (IP + start address) add hota hai.

Agar kisi specific panel ka Area/Device-ID/Port default se alag ho (bahut
rare case - normally sabka same hota hai), to us panel ki integration entry
open karke "CONFIGURE" (Options) se override kar sakte ho.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from . import protocol
from .const import (
    CONF_AREA,
    CONF_DEVICE_ID,
    CONF_IP,
    CONF_PANEL_NAME,
    CONF_PORT,
    CONF_START_ADDRESS,
    DEFAULT_AREA,
    DEFAULT_DEVICE_ID,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP): str,
        vol.Required(CONF_START_ADDRESS): str,
        vol.Optional(CONF_PANEL_NAME, default=""): str,
    }
)


class RaylogicH81ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Bas ek step: IP aur Start Address lo, baaki khud calculate/set ho jaata hai."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            ip = user_input[CONF_IP].strip()
            raw_start_address = user_input[CONF_START_ADDRESS].strip()

            if not ip:
                errors[CONF_IP] = "invalid_ip"
            else:
                try:
                    base_channel = protocol.parse_start_address(raw_start_address)
                    if not (0 < base_channel <= 0xFFF8):
                        raise ValueError("start address out of range")
                except (ValueError, TypeError):
                    errors[CONF_START_ADDRESS] = "invalid_start_address"
                else:
                    # Ek hi ip+start_address dobara add na ho jaaye
                    unique_id = f"{ip}_{base_channel}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    panel_name = user_input.get(CONF_PANEL_NAME) or f"Raylogic H81 {ip}"

                    return self.async_create_entry(
                        title=panel_name,
                        data={
                            CONF_IP: ip,
                            CONF_START_ADDRESS: raw_start_address,
                            CONF_PANEL_NAME: panel_name,
                            CONF_PORT: DEFAULT_PORT,
                            CONF_AREA: DEFAULT_AREA,
                            CONF_DEVICE_ID: DEFAULT_DEVICE_ID,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "RaylogicH81OptionsFlow":
        return RaylogicH81OptionsFlow(config_entry)


class RaylogicH81OptionsFlow(config_entries.OptionsFlow):
    """Advanced overrides (Port/Area/Device-ID) - normally chhedne ki zaroorat nahi."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = self.config_entry.data
        options = self.config_entry.options

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_PORT,
                    default=options.get(CONF_PORT, data.get(CONF_PORT, DEFAULT_PORT)),
                ): int,
                vol.Optional(
                    CONF_AREA,
                    default=options.get(CONF_AREA, data.get(CONF_AREA, DEFAULT_AREA)),
                ): str,
                vol.Optional(
                    CONF_DEVICE_ID,
                    default=options.get(CONF_DEVICE_ID, data.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID)),
                ): int,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
