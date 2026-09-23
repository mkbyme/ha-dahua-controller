"""Preset select entity for Dahua Controller."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import DahuaRuntimeData
from .const import DOMAIN
from .entity import DahuaControllerEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: DahuaRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DahuaPresetSelect(runtime, entry)])


class DahuaPresetSelect(DahuaControllerEntity, RestoreEntity, SelectEntity):
    """Selecting an option moves the camera to that PTZ preset."""

    _attr_name = "Preset"
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(self, runtime: DahuaRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator, entry)
        self._client = runtime.client
        self._attr_unique_id = f"{entry.unique_id}_preset_select"
        self._current_option: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self.options:
            self._current_option = last_state.state

    @property
    def options(self) -> list[str]:
        return [p.name for p in self.coordinator.presets]

    @property
    def current_option(self) -> str | None:
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        ok = await self._client.goto_preset_by_name(option, self.coordinator.presets)
        if ok:
            self._current_option = option
            self.async_write_ha_state()
