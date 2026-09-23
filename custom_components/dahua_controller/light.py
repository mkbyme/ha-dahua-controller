"""Spotlight light entity for Dahua Controller.

See const.LIGHT_TABLE for the unverified-assumption caveat about which
config table index actually drives the visible spotlight vs. the IR
illuminator on this hardware.
"""

from __future__ import annotations

import logging

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DahuaRuntimeData
from .const import DOMAIN
from .entity import DahuaControllerEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: DahuaRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DahuaSpotlight(runtime, entry)])


class DahuaSpotlight(DahuaControllerEntity, LightEntity):
    """Camera spotlight, brightness-only (0-100 scaled to HA's 0-255)."""

    _attr_name = "Spotlight"
    _attr_icon = "mdi:spotlight-beam"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, runtime: DahuaRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator, entry)
        self._client = runtime.client
        self._attr_unique_id = f"{entry.unique_id}_spotlight"

    @property
    def is_on(self) -> bool:
        status = self.coordinator.data.light_status
        return status.mode == "Manual" and status.level > 0

    @property
    def brightness(self) -> int:
        level = self.coordinator.data.light_status.level
        return round(level * 255 / 100)

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get("brightness")
        level = round(brightness * 100 / 255) if brightness is not None else 100
        await self._client.light_set(on=True, level=level)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self._client.light_set(on=False, level=0)
        await self.coordinator.async_request_refresh()
