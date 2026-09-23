"""Data update coordinator for a single Dahua camera."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .dahua_client import AudioCapabilities, DahuaClient, LightStatus, Preset
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class DahuaData:
    """Data refreshed on every poll cycle."""

    light_status: LightStatus = field(default_factory=LightStatus)
    alarm_enabled: bool = False


class DahuaCoordinator(DataUpdateCoordinator[DahuaData]):
    """Polls light + active-deterrence state on an interval.

    Presets and audio capabilities are deliberately NOT part of the periodic
    poll: presets only change when a human re-teaches a position (fetched
    once at setup via `async_initialize`, refreshed on-demand via
    `async_refresh_presets` from the "Sync presets" button), and audio
    capabilities are fixed hardware facts probed once at setup to decide
    whether to create the media_player entity at all.
    """

    def __init__(self, hass: HomeAssistant, client: DahuaClient, update_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.client = client
        self.presets: list[Preset] = []
        self.audio_caps: AudioCapabilities = AudioCapabilities()

    async def async_initialize(self) -> None:
        """One-time setup fetches, run before the first periodic refresh."""
        self.presets = await self.client.fetch_presets()
        self.audio_caps = await self.client.probe_audio()

    async def async_refresh_presets(self) -> None:
        """On-demand preset re-fetch, triggered by the sync_presets button."""
        self.presets = await self.client.fetch_presets()
        self.async_update_listeners()

    async def _async_update_data(self) -> DahuaData:
        light_status = await self.client.light_get_status()
        alarm_enabled = await self.client.alarm_get_status()
        return DahuaData(light_status=light_status, alarm_enabled=alarm_enabled)
