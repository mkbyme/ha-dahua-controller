"""The Dahua Controller integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import (
    CONF_AUDIO_MAX_GAIN,
    CONF_CHANNEL,
    DEFAULT_AUDIO_GAIN,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import DahuaCoordinator
from .dahua_client import DahuaClient, DahuaClientError

_LOGGER = logging.getLogger(__name__)


@dataclass
class DahuaRuntimeData:
    """Objects shared across this entry's platforms."""

    client: DahuaClient
    coordinator: DahuaCoordinator


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_CREATE_PRESET = "create_preset"
SERVICE_GET_PRESETS = "get_presets"
ATTR_DEVICE_ID = "device_id"
ATTR_PRESET_NUMBER = "preset_number"
ATTR_NAME = "name"

CREATE_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_NAME): vol.All(cv.string, vol.Strip, vol.Length(min=1, max=64)),
        vol.Optional(ATTR_PRESET_NUMBER): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
    }
)
GET_PRESETS_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-level actions."""

    async def _create_preset(call: ServiceCall) -> ServiceResponse:
        runtime = _runtime_for_device(hass, call.data[ATTR_DEVICE_ID])
        coordinator = runtime.coordinator
        # Re-read first so slot/name collisions are checked against the camera.
        await coordinator.async_refresh_presets()
        try:
            preset = await runtime.client.set_preset(
                call.data[ATTR_NAME],
                coordinator.presets,
                call.data.get(ATTR_PRESET_NUMBER),
            )
        except DahuaClientError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            await coordinator.async_refresh_presets()
        return {
            "preset_number": preset.index,
            "name": preset.name,
            **coordinator.preset_summary(),
        }

    async def _get_presets(call: ServiceCall) -> ServiceResponse:
        coordinator = _runtime_for_device(hass, call.data[ATTR_DEVICE_ID]).coordinator
        await coordinator.async_refresh_presets()  # live read, not the cached list
        return coordinator.preset_summary()

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_PRESET,
        _create_preset,
        schema=CREATE_PRESET_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PRESETS,
        _get_presets,
        schema=GET_PRESETS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


def _runtime_for_device(hass: HomeAssistant, device_id: str) -> DahuaRuntimeData:
    device = dr.async_get(hass).async_get(device_id)
    if device is not None:
        for entry_id in device.config_entries:
            runtime = hass.data.get(DOMAIN, {}).get(entry_id)
            if runtime is not None:
                return runtime
    raise ServiceValidationError(f"Device {device_id} is not a loaded Dahua Controller camera")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dahua Controller from a config entry."""
    client = DahuaClient(
        hass,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        channel=entry.data[CONF_CHANNEL],
        audio_gain=entry.options.get(CONF_AUDIO_MAX_GAIN, DEFAULT_AUDIO_GAIN),
    )

    coordinator = DahuaCoordinator(hass, client)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = DahuaRuntimeData(
        client=client, coordinator=coordinator
    )

    _remove_legacy_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


def _remove_legacy_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop registry entries for entities this integration no longer creates,
    so they don't linger as "unavailable" after an upgrade.
    """
    registry = er.async_get(hass)
    for platform, suffix in (("switch", "active_deterrence"),):
        entity_id = registry.async_get_entity_id(
            platform, DOMAIN, f"{entry.unique_id}_{suffix}"
        )
        if entity_id:
            registry.async_remove(entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry (options changed)."""
    await hass.config_entries.async_reload(entry.entry_id)
