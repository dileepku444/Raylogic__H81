"""Raylogic H81 8-channel dimmer integration - config-entry (UI) based.

HACS se install karne ke baad, Settings -> Devices & Services -> Add
Integration -> "Raylogic H81" se ek naya panel add karo (sirf IP + Start
Address maanga jaata hai). Har panel ke 8 channel numbers start address se
khud calculate hote hain (dekho custom_components/raylogic_h81/protocol.py
mein channels_for_start_address()).
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Ek panel (config entry) setup karo."""
    hass.data.setdefault(DOMAIN, {})
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Panel remove/reload hone par platforms unload karo."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options (Port/Area/Device-ID) change hone par integration reload karo."""
    await hass.config_entries.async_reload(entry.entry_id)
