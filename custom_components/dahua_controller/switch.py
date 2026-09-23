"""Active Deterrence switch for Dahua Controller.

Active Deterrence is the camera's own auto light+speaker+voice feature that
triggers on motion/person detection - this switch is the master on/off for
that camera-side feature, not a per-alert toggle.
"""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities([DahuaActiveDeterrenceSwitch(runtime, entry)])


class DahuaActiveDeterrenceSwitch(DahuaControllerEntity, SwitchEntity):
    """On/off for the camera's Active Deterrence feature."""

    _attr_name = "Active Deterrence"
    _attr_icon = "mdi:shield-alert"

    def __init__(self, runtime: DahuaRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator, entry)
        self._client = runtime.client
        self._attr_unique_id = f"{entry.unique_id}_active_deterrence"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.alarm_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self._client.alarm_set(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self._client.alarm_set(False)
        await self.coordinator.async_request_refresh()
