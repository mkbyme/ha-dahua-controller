"""Button entities for Dahua Controller: PTZ movement, stop, beep alert, sync presets,
PTZ calibration."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DahuaRuntimeData
from .const import (
    BUTTON_DIRECTIONS,
    CONF_PTZ_DURATION,
    CONF_PTZ_SPEED,
    CONF_PTZ_STEPS,
    DEFAULT_DURATION,
    DEFAULT_SPEED,
    DEFAULT_STEPS,
    DEFAULT_TONE_DURATION,
    DEFAULT_TONE_FREQ,
    DOMAIN,
)
from .entity import DahuaControllerEntity

_LOGGER = logging.getLogger(__name__)

_DIRECTION_LABELS = {
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: DahuaRuntimeData = hass.data[DOMAIN][entry.entry_id]

    entities: list[ButtonEntity] = [
        DahuaMoveButton(runtime, entry, direction) for direction in BUTTON_DIRECTIONS
    ]
    entities.append(DahuaStopButton(runtime, entry))
    entities.append(DahuaAlertTestButton(runtime, entry))
    entities.append(DahuaSyncPresetsButton(runtime, entry))
    entities.append(DahuaCalibrateButton(runtime, entry))
    async_add_entities(entities)


class DahuaMoveButton(DahuaControllerEntity, ButtonEntity):
    """Step-move in one direction (start -> sleep -> stop).

    HA button entities only support a single momentary press, not
    press-and-hold, so this reuses the step-move semantics rather than the
    continuous start/stop CGI calls.
    """

    def __init__(self, runtime: DahuaRuntimeData, entry: ConfigEntry, direction: str) -> None:
        super().__init__(runtime.coordinator, entry)
        self._client = runtime.client
        self._entry = entry
        self._direction = direction
        self._attr_name = f"PTZ {_DIRECTION_LABELS[direction]}"
        self._attr_unique_id = f"{entry.unique_id}_ptz_{direction}"
        self._attr_icon = f"mdi:arrow-{direction}-bold"

    async def async_press(self) -> None:
        options = self._entry.options
        await self._client.ptz_move(
            direction=self._direction,
            steps=options.get(CONF_PTZ_STEPS, DEFAULT_STEPS),
            speed=options.get(CONF_PTZ_SPEED, DEFAULT_SPEED),
            duration=options.get(CONF_PTZ_DURATION, DEFAULT_DURATION),
        )


class DahuaStopButton(DahuaControllerEntity, ButtonEntity):
    """Immediately halt PTZ movement in every direction, regardless of what
    might currently be mid-motion.
    """

    _attr_name = "PTZ Stop"
    _attr_icon = "mdi:stop"

    def __init__(self, runtime: DahuaRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator, entry)
        self._client = runtime.client
        self._attr_unique_id = f"{entry.unique_id}_ptz_stop"

    async def async_press(self) -> None:
        await self._client.ptz_stop_all()


class DahuaAlertTestButton(DahuaControllerEntity, ButtonEntity):
    """Play a one-shot beep tone through the camera speaker."""

    _attr_name = "Play Alert Tone"
    _attr_icon = "mdi:bullhorn"

    def __init__(self, runtime: DahuaRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator, entry)
        self._client = runtime.client
        self._attr_unique_id = f"{entry.unique_id}_alert_test"

    async def async_press(self) -> None:
        await self._client.play_tone(DEFAULT_TONE_FREQ, DEFAULT_TONE_DURATION)


class DahuaSyncPresetsButton(DahuaControllerEntity, ButtonEntity):
    """Re-fetch the preset list from the camera on demand."""

    _attr_name = "Sync Presets"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: DahuaRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator, entry)
        self._attr_unique_id = f"{entry.unique_id}_sync_presets"

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_presets()


class DahuaCalibrateButton(DahuaControllerEntity, ButtonEntity):
    """Run the camera's PTZ self-check ("PTZ Restart") to re-find its mechanical zero.

    Fixes presets that land off-target after a power cut or network drop
    mid-move (the motor's position memory no longer matches reality). The
    camera sweeps its full pan/tilt range (~1 min) before it settles; saved
    presets are kept. See `DahuaClient.ptz_calibrate` for the transport
    fallback order (RPC2 over HTTP -> RPC2 over DHIP/37777 -> legacy CGI).
    """

    _attr_name = "PTZ Calibrate"
    _attr_icon = "mdi:crosshairs-gps"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: DahuaRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator, entry)
        self._client = runtime.client
        self._attr_unique_id = f"{entry.unique_id}_ptz_calibrate"
        self._attr_extra_state_attributes = {}

    async def async_press(self) -> None:
        used, errors = await self._client.ptz_calibrate()
        self._attr_extra_state_attributes = {"last_method": used, "last_errors": errors}
        self.async_write_ha_state()
        if not used:
            raise HomeAssistantError(
                "Camera rejected the PTZ self-check on every transport: " + " | ".join(errors)
            )
        _LOGGER.info("PTZ calibrate accepted via %s", used)
