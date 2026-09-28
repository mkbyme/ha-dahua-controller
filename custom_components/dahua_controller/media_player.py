"""Speaker media_player entity for Dahua Controller.

Supported sources:
- Local media files via Home Assistant Media Source
- TTS audio streams
- Remote URLs via HTTP/HTTPS
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import struct

from homeassistant.components import media_source
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.components.media_player import (
    BrowseMedia,
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

from homeassistant.components.media_player.browse_media import (
    async_process_play_media_url,
)


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
    """Camera speaker as an HA media_player (play_media / tts.speak / media_source target)."""

    _attr_name = "Speaker"
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    # Kích hoạt tính năng Browse Media cùng Play Media
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.BROWSE_MEDIA
    )

    def __init__(self, hass: HomeAssistant, runtime: DahuaRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator, entry)
        self._hass = hass
        self._client = runtime.client
        self._attr_unique_id = f"{entry.unique_id}_speaker"
        self._attr_state = MediaPlayerState.IDLE

    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        """Hỗ trợ giao diện chọn file từ Media Browser trên HA UI."""
        return await media_source.async_browse_media(
            self._hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

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
        """Fetch media bytes from media_source, local filesystem, or external HTTP URL."""
        url = media_id

        # 1. Resolve media-source:// URI (TTS, local media browser, etc.)
        if media_source.is_media_source_id(url):
            resolved = await media_source.async_resolve_media(self._hass, url, self.entity_id)
            url = resolved.url

        # 2. Xử lý đường dẫn /media/local/... trực tiếp từ Disk (Fast Path & tránh HTTP 401)
        if url.startswith("/media/local/"):
            relative_path = url.removeprefix("/media/local/")
            # Mặc định thư mục /media/local tương ứng với folder media/ trong HA config
            disk_path = Path(self._hass.config.path("media", relative_path))
            if await self._hass.async_add_executor_job(disk_path.is_file):
                _LOGGER.debug("Reading media directly from disk: %s", disk_path)
                return await self._hass.async_add_executor_job(disk_path.read_bytes)

        # 3. Ký Auth Token cho URL nội bộ (/media/..., /api/...) để tránh lỗi HTTP 401 Unauthorized
        if url.startswith("/"):
            url = async_process_play_media_url(self._hass, url)
            if url.startswith("/"):
                url = get_url(self._hass, prefer_external=False) + url

        # 4. Fetch qua HTTP Client Session đối với URL đã có Signature Token hoặc URL ngoài
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
                "ffmpeg binary not found - required to play non-WAV media (e.g. mp3/flac) "
                "through the camera speaker"
            ) from err

        stdout, stderr = await proc.communicate(input=raw)
        if proc.returncode != 0 or not stdout:
            _LOGGER.debug("ffmpeg stderr: %s", stderr.decode(errors="replace"))
            raise HomeAssistantError("Failed to decode media for camera speaker")

        samples = struct.unpack(f"<{len(stdout) // 2}h", stdout[: len(stdout) - (len(stdout) % 2)])
        return pcm16_to_alaw(samples)
