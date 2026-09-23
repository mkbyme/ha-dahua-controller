"""The Dahua Controller integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant

from .const import CONF_CHANNEL, DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
from .coordinator import DahuaCoordinator
from .dahua_client import DahuaClient

_LOGGER = logging.getLogger(__name__)


@dataclass
class DahuaRuntimeData:
    """Objects shared across this entry's platforms."""

    client: DahuaClient
    coordinator: DahuaCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dahua Controller from a config entry."""
    client = DahuaClient(
        hass,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        channel=entry.data[CONF_CHANNEL],
    )

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = DahuaCoordinator(hass, client, scan_interval)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = DahuaRuntimeData(
        client=client, coordinator=coordinator
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry (options changed)."""
    await hass.config_entries.async_reload(entry.entry_id)
