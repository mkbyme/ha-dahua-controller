"""Speaker volume number entity for Dahua Controller.

EXPERIMENTAL: see DahuaClient.speaker_volume_set / DahuaNetSDKTalk.volume for
why this is a best-effort NetSDK "Volume" field on the Talk.General talk
session, not a confirmed camera-wide hardware volume control - there is no
way to read the camera's actual output level back, so this entity's state is
just "the value we'll ask for next," not a confirmed hardware readout.
"""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DahuaRuntimeData
from .const import DEFAULT_SPEAKER_VOLUME, DOMAIN
from .entity import DahuaControllerEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: DahuaRuntimeData = hass.data[DOMAIN][entry.entry_id]
    if not runtime.coordinator.audio_caps.has_speaker:
        _LOGGER.info(
            "Camera '%s' reports no speaker channel - skipping speaker volume entity",
            entry.title,
        )
        return
    async_add_entities([DahuaSpeakerVolume(runtime, entry)])


class DahuaSpeakerVolume(DahuaControllerEntity, NumberEntity):
    """Best-effort speaker output volume (0-100) - see module docstring."""

    _attr_name = "Speaker Volume"
    _attr_icon = "mdi:volume-high"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1

    def __init__(self, runtime: DahuaRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator, entry)
        self._client = runtime.client
        self._attr_unique_id = f"{entry.unique_id}_speaker_volume"
        self._attr_native_value = DEFAULT_SPEAKER_VOLUME

    async def async_set_native_value(self, value: float) -> None:
        await self._client.speaker_volume_set(int(value))
        self._attr_native_value = value
        self.async_write_ha_state()
