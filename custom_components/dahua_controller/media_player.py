"""Speaker media_player entity for Dahua Controller.

Makes the camera speaker a valid `tts.speak`/`media_player.play_media` target,
replacing the old pyscript `cam_speak`'s workaround of calling HA's internal
TTS API directly. Two source formats are supported:

- WAV (RIFF/WAVE container, PCM16): decoded with the existing pure-Python
  pipeline in dahua_client.py (no external dependency).
- Anything else (mp3, the default output of most TTS engines, etc.): piped
  through ffmpeg (HA core's `ffmpeg` integration resolves the binary) to get
  raw PCM16 8kHz mono directly, skipping the WAV container parsing and the
  pure-Python resampler for this path.

Both paths converge on the same G.711 A-law encoder before POSTing to the
camera's audio.cgi.
"""

from __future__ import annotations

import asyncio
import logging
import struct

from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.network import get_url

from . import DahuaRuntimeData
from .const import DOMAIN
from .dahua_client import is_wav, pcm16_to_alaw, wav_bytes_to_alaw
from .entity import DahuaControllerEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: DahuaRuntimeData = hass.data[DOMAIN][entry.entry_id]
    if not runtime.coordinator.audio_caps.has_speaker:
        _LOGGER.info(
            "Camera '%s' reports no speaker channel - skipping media_player entity",
            entry.title,
        )
        return
    async_add_entities([DahuaSpeaker(hass, runtime, entry)])


class DahuaSpeaker(DahuaControllerEntity, MediaPlayerEntity):
    """Camera speaker as an HA media_player (play_media / tts.speak target)."""

    _attr_name = "Speaker"
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = MediaPlayerEntityFeature.PLAY_MEDIA

    def __init__(self, hass: HomeAssistant, runtime: DahuaRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator, entry)
        self._hass = hass
        self._client = runtime.client
        self._attr_unique_id = f"{entry.unique_id}_speaker"
        self._attr_state = MediaPlayerState.IDLE

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()
        try:
            raw = await self._fetch_media_bytes(media_id)
            alaw = await self._decode_to_alaw(raw)
            ok = await self._client.play_media_bytes(alaw)
            if not ok:
                raise HomeAssistantError("Camera rejected the audio stream")
        finally:
            self._attr_state = MediaPlayerState.IDLE
            self.async_write_ha_state()

    async def _fetch_media_bytes(self, media_id: str) -> bytes:
        url = media_id
        if url.startswith("/"):
            url = get_url(self._hass, prefer_external=False) + url
        session = async_get_clientsession(self._hass)
        async with session.get(url) as resp:
            if resp.status != 200:
                raise HomeAssistantError(f"Failed to fetch media ({resp.status}): {url}")
            return await resp.read()

    async def _decode_to_alaw(self, raw: bytes) -> bytes:
        if is_wav(raw):
            return wav_bytes_to_alaw(raw)
        return await self._decode_via_ffmpeg(raw)

    async def _decode_via_ffmpeg(self, raw: bytes) -> bytes:
        manager = get_ffmpeg_manager(self._hass)
        binary = manager.binary
        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-ar",
                "8000",
                "-ac",
                "1",
                "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as err:
            raise HomeAssistantError(
                "ffmpeg binary not found - required to play non-WAV media (e.g. mp3 TTS "
                "output) through the camera speaker"
            ) from err

        stdout, stderr = await proc.communicate(input=raw)
        if proc.returncode != 0 or not stdout:
            _LOGGER.debug("ffmpeg stderr: %s", stderr.decode(errors="replace"))
            raise HomeAssistantError("Failed to decode media for camera speaker")

        samples = struct.unpack(f"<{len(stdout) // 2}h", stdout[: len(stdout) - (len(stdout) % 2)])
        return pcm16_to_alaw(samples)
