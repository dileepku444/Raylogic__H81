"""Raylogic H81 light platform - config entry se 8 channel entities banata hai.

Setup wizard (config_flow.py) se sirf IP aur Start Address aati hai. Yahan
us start address se 8 channel numbers calculate karke, har channel ke liye
ek HA light entity banayi jaati hai.
"""
from __future__ import annotations

import logging

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Ek panel (config entry) ke 8 channels ko HA light entities banao."""
    data = entry.data
    options = entry.options

    ip = data[CONF_IP]
    port = options.get(CONF_PORT, data.get(CONF_PORT, DEFAULT_PORT))
    area = options.get(CONF_AREA, data.get(CONF_AREA, DEFAULT_AREA))
    device_id = options.get(CONF_DEVICE_ID, data.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID))
    start_address = data[CONF_START_ADDRESS]
    panel_name = data.get(CONF_PANEL_NAME) or f"Raylogic H81 {ip}"

    device = protocol.get_device(ip, port, area=area, device_id=device_id, name=panel_name)
    # Socket connect blocking hai - executor mein chalao taaki event loop na ruke.
    await hass.async_add_executor_job(device.ensure_started)

    # <<< YAHI CALCULATION HAI: start address se 8 channel numbers >>>
    channels = protocol.channels_for_start_address(start_address)
    _LOGGER.info(
        "Raylogic H81 [%s] %s:%s - start_address=%s se channels %s",
        panel_name, ip, port, start_address, channels,
    )

    entities = [
        RaylogicChannel(
            f"{panel_name} D1" if idx == 1 else f"{panel_name} {idx}",
            device,
            channel,
        )
        for idx, channel in enumerate(channels, start=1)
    ]
    async_add_entities(entities, True)


class RaylogicChannel(LightEntity):
    """Ek H81 dimmer channel = ek HA light entity."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    # Push-based: protocol.py se listener callback aane pe khud
    # schedule_update_ha_state() karte hain, isliye periodic polling nahi
    # chahiye.
    _attr_should_poll = False

    def __init__(
        self,
        name: str,
        device: "protocol.RaylogicDevice",
        channel: int,
    ) -> None:
        self._attr_name = name
        self._device = device
        self._channel = channel
        self._attr_unique_id = f"raylogic_h81_{device.key}_ch{channel}"
        self._attr_is_on = False
        self._attr_brightness = 0
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device.key)},
            "name": device.name,
            "manufacturer": "Raylogic",
            "model": "DIN-H81",
        }

    async def async_added_to_hass(self) -> None:
        """Entity HA mein add hote hi apne device+channel ka feedback listener register karo."""
        self._device.register_listener(self._channel, self._handle_external_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity remove hone pe listener saaf karo (stale callback na reh jaye)."""
        self._device.unregister_listener(self._channel, self._handle_external_update)

    def _handle_external_update(self, level_percent: int) -> None:
        """
        protocol.py ke receive-loop se callback - jab bhi is channel ka
        *AR= frame kahin se bhi aaye (mobile app se, panel se, ya khud
        HA ke apne command ka loopback), turant entity ka state sync karo
        aur HA UI ko update karo. Ye kisi bhi thread se call ho sakta hai,
        isliye schedule_update_ha_state() use karte hain (thread-safe).
        """
        is_on = level_percent > 0
        brightness = round((level_percent / 100) * 255) if is_on else 0
        if is_on:
            brightness = max(1, brightness)
        self._attr_is_on = is_on
        self._attr_brightness = brightness
        self.schedule_update_ha_state()

    def turn_on(self, **kwargs) -> None:
        brightness = kwargs.get("brightness", 255)
        percent = round((brightness / 255) * 100)
        # JUGAAD (aapse confirm kiya gaya): HA ka brightness slider 1-255
        # range mein hota hai, kabhi 0 nahi bhejta - isliye slider ko
        # ekdum neeche (1%) tak drag karne par bhi light "on, bahut dim"
        # rehti thi, poora OFF kabhi nahi hoti thi. Ab agar computed percent
        # <=1% aata hai, to seedha turn_off() call kar dete hain (device ko
        # LEVEL_OFF/FF bhejta hai) - taaki HA aur mobile app dono mein
        # slider ka sabse neeche wala point matlab "poora OFF" ho, jaisa
        # mobile app mein already hota hai.
        if percent <= 1:
            self.turn_off()
            return
        try:
            self._device.set_channel_level(self._channel, percent)
            self._attr_is_on = True
            self._attr_brightness = brightness
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Raylogic channel %s ON command fail: %s", self._channel, err)
            return
        # ZAROORI: should_poll=False hone ki wajah se HA khud-ba-khud state
        # write nahi karta service call ke baad - humein khud batana padta
        # hai.
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs) -> None:
        try:
            self._device.set_channel_level(self._channel, 0)
            self._attr_is_on = False
            self._attr_brightness = 0
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Raylogic channel %s OFF command fail: %s", self._channel, err)
            return
        self.schedule_update_ha_state()
