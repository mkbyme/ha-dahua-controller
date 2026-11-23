"""Data update coordinator for a single Dahua camera."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .dahua_client import AudioCapabilities, DahuaClient, Preset
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class DahuaCoordinator(DataUpdateCoordinator[None]):
    """Shared per-camera state holder; nothing is polled periodically.

    Presets only change when a human re-teaches a position (fetched once at
    setup via `async_initialize`, refreshed on-demand via
    `async_refresh_presets` from the "Sync presets" button), and audio
    capabilities are fixed hardware facts probed once at setup to decide
    whether to create the media_player entity at all.
    """

    def __init__(self, hass: HomeAssistant, client: DahuaClient) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.client = client
        self.presets: list[Preset] = []
        self.audio_caps: AudioCapabilities = AudioCapabilities()

    async def async_initialize(self) -> None:
        """One-time setup fetches."""
        self.presets = await self.client.fetch_presets()
        self.audio_caps = await self.client.probe_audio()

    async def async_refresh_presets(self) -> None:
        """On-demand preset re-fetch, triggered by the sync_presets button."""
        self.presets = await self.client.fetch_presets()
        self.async_update_listeners()

    async def _async_update_data(self) -> None:
        return None
