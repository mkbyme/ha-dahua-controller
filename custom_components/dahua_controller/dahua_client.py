"""Dahua camera HTTP CGI client: digest auth, PTZ, presets, audio, light, alarm.

Ported from the original pyscript `ptz_control.py`. The digest-auth computation,
the "setConfig always returns HTTP 400 even on success" quirk, and the "audio POST
closes the socket with no HTTP response on success" quirk were all hand-verified
against a real device (DH-P5D-5F-PV) - see the CLAUDE.md in the source pyscript repo
for the verification notes. Do not "fix" these away; they are the actual protocol
behavior of this hardware, not bugs in this client.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import math
import os
import struct
import wave
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import ALARM_TABLE, DIRECTION_MAP, LIGHT_TABLE

_LOGGER = logging.getLogger(__name__)


class DahuaClientError(Exception):
    """Base error for Dahua client operations."""


class DahuaAuthError(DahuaClientError):
    """Raised when digest auth is rejected (wrong username/password)."""


class DahuaConnectionError(DahuaClientError):
    """Raised when the camera cannot be reached at all."""


@dataclass
class Preset:
    """A single PTZ preset as reported by the camera."""

    name: str
    index: int


@dataclass
class LightStatus:
    """Current spotlight config readback."""

    mode: str | None = None
    level: int = 0


@dataclass
class AudioCapabilities:
    """Result of probing devAudioInput.cgi/devAudioOutput.cgi."""

    input_channels: int = 0
    output_channels: int = 0

    @property
    def has_speaker(self) -> bool:
        return self.output_channels > 0


# ─────────────────────────────────────────────────────
# G.711 A-law encode + resample (pure Python, no audioop/numpy/ffmpeg for
# this path - the WAV path stays sandbox-friendly; mp3 goes through ffmpeg
# in media_player.py instead of here).
# ─────────────────────────────────────────────────────
_ALAW_SEG_END = [0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF]


def _alaw_search(val: int) -> int:
    for i, seg in enumerate(_ALAW_SEG_END):
        if val <= seg:
            return i
    return len(_ALAW_SEG_END)


def _linear_to_alaw(pcm_val: int) -> int:
    """Encode 1 PCM16 (signed) sample -> 1 byte G.711 A-law (ITU-T G.711).

    Verified byte-identical to the deprecated stdlib `audioop.lin2alaw`
    across the full 16-bit range - do not rederive/"simplify" this.
    """
    pcm_val = max(-32768, min(32767, pcm_val)) >> 3

    if pcm_val >= 0:
        mask = 0xD5
    else:
        mask = 0x55
        pcm_val = -pcm_val - 1

    seg = _alaw_search(pcm_val)
    if seg >= 8:
        return 0x7F ^ mask

    aval = seg << 4
    if seg < 2:
        aval |= (pcm_val >> 1) & 0xF
    else:
        aval |= (pcm_val >> seg) & 0xF
    return aval ^ mask


def pcm16_to_alaw(samples) -> bytes:
    """Encode an iterable of signed 16-bit samples to G.711 A-law bytes."""
    return bytes(_linear_to_alaw(s) for s in samples)


def _resample_pcm16(samples, src_rate: int, dst_rate: int = 8000):
    """Nearest-neighbor resample of mono PCM16 - only used for the WAV path.

    The ffmpeg/mp3 path in media_player.py has ffmpeg do its own resampling,
    so this is intentionally not reused there.
    """
    if src_rate == dst_rate or not samples:
        return samples
    src_n = len(samples)
    dst_n = int(src_n * dst_rate / src_rate)
    return [samples[min(src_n - 1, int(i * src_rate / dst_rate))] for i in range(dst_n)]


def _gen_tone_alaw(freq: float, duration: float, rate: int = 8000, amplitude: int = 9000) -> bytes:
    """Generate a sine tone (PCM16 -> A-law) for the speaker beep test."""
    n = int(rate * duration)
    samples = [int(amplitude * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    return pcm16_to_alaw(samples)


def wav_bytes_to_alaw(data: bytes) -> bytes:
    """Decode WAV (PCM16, mono/stereo, any sample rate) from an in-RAM buffer,
    resample to 8kHz mono, and encode to G.711 A-law for the camera speaker.
    """
    with wave.open(io.BytesIO(data), "rb") as w:
        n_channels = w.getnchannels()
        sample_width = w.getsampwidth()
        frame_rate = w.getframerate()
        raw = w.readframes(w.getnframes())

    if sample_width != 2:
        raise ValueError(f"Chỉ hỗ trợ WAV PCM16, file này sample_width={sample_width * 8}bit")

    samples = list(struct.unpack(f"<{len(raw) // 2}h", raw))

    if n_channels == 2:
        samples = [(samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples) - 1, 2)]
    elif n_channels != 1:
        raise ValueError(f"Chỉ hỗ trợ mono/stereo, file này có {n_channels} channels")

    samples = _resample_pcm16(samples, frame_rate, 8000)
    return pcm16_to_alaw(samples)


def is_wav(data: bytes) -> bool:
    """Sniff whether a buffer looks like a RIFF/WAVE container."""
    return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WAVE"


class DahuaClient:
    """Thin async client for one Dahua camera's HTTP CGI surface."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        username: str,
        password: str,
        channel: int,
    ) -> None:
        self._session = async_get_clientsession(hass)
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._channel = channel
        # Serializes all CGI calls: the pyscript original ran effectively one
        # call at a time, but a multi-platform integration can fire a
        # coordinator poll and a button press concurrently against the same
        # digest nonce/nc sequence, which could otherwise race and 401.
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def channel(self) -> int:
        return self._channel

    # ─────────────────────────────────────────────────
    # Digest auth core
    # ─────────────────────────────────────────────────
    @staticmethod
    def _parse_digest_header(header: str) -> dict[str, str]:
        result: dict[str, str] = {}
        try:
            for part in header.replace("Digest ", "").split(","):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    result[k.strip()] = v.strip().strip('"')
        except Exception as err:  # noqa: BLE001 - mirrors original defensive parsing
            _LOGGER.warning("Parse WWW-Authenticate lỗi: %s", err)
        return result

    def _build_digest_header(self, method: str, uri: str, www_auth: str) -> str:
        d = self._parse_digest_header(www_auth)
        realm = d.get("realm", "")
        nonce = d.get("nonce", "")
        qop = d.get("qop", "")
        opaque = d.get("opaque", "")

        ha1 = hashlib.md5(f"{self._username}:{realm}:{self._password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        nc = "00000001"
        cnonce = base64.b64encode(os.urandom(8)).decode()[:8]

        if qop == "auth":
            resp = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
            return (
                f'Digest username="{self._username}", realm="{realm}", '
                f'nonce="{nonce}", uri="{uri}", qop={qop}, '
                f'nc={nc}, cnonce="{cnonce}", response="{resp}"'
                + (f', opaque="{opaque}"' if opaque else "")
            )

        resp = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        return (
            f'Digest username="{self._username}", realm="{realm}", '
            f'nonce="{nonce}", uri="{uri}", response="{resp}"'
            + (f', opaque="{opaque}"' if opaque else "")
        )

    async def _digest_get(self, path_and_query: str) -> tuple[int, str]:
        """GET with digest auth. Returns (status_code, body_text); status -1 on
        connection/timeout failure before any HTTP status was ever received.
        """
        url = f"{self.base_url}{path_and_query}"
        async with self._lock:
            try:
                try:
                    async with self._session.get(
                        url, timeout=aiohttp.ClientTimeout(total=5)
                    ) as r1:
                        if r1.status != 401:
                            return r1.status, await r1.text()
                        www_auth = r1.headers.get("WWW-Authenticate", "")
                except aiohttp.ClientConnectorError as err:
                    _LOGGER.error("[_digest_get] Connection refused: %s → %s", url, err)
                    return -1, ""
                except aiohttp.ServerTimeoutError:
                    _LOGGER.error("[_digest_get] Timeout (step1): %s", url)
                    return -1, ""

                if not www_auth:
                    _LOGGER.error("[_digest_get] 401 nhưng không có WWW-Authenticate: %s", url)
                    return 401, ""

                parsed = urlparse(url)
                uri = parsed.path + ("?" + parsed.query if parsed.query else "")
                try:
                    auth_header = self._build_digest_header("GET", uri, www_auth)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("[_digest_get] Tính Digest hash lỗi: %s", err)
                    return -1, ""

                try:
                    async with self._session.get(
                        url,
                        headers={"Authorization": auth_header},
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as r2:
                        return r2.status, await r2.text()
                except aiohttp.ServerTimeoutError:
                    _LOGGER.error("[_digest_get] Timeout (step2): %s", url)
                    return -1, ""
                except aiohttp.ClientConnectorError as err:
                    _LOGGER.error("[_digest_get] Connection error (step2): %s", err)
                    return -1, ""
            except Exception as err:  # noqa: BLE001 - mirrors original catch-all
                _LOGGER.error(
                    "[_digest_get] Unexpected error: %s → %s: %s", url, type(err).__name__, err
                )
                return -1, ""

    async def _digest_post(self, path_and_query: str, body: bytes, content_type: str) -> bool:
        """POST with digest auth, used only for audio.cgi?action=postAudioStream.

        Dahua accepts the full body then closes the socket with NO HTTP response
        at all on success - this raises ServerDisconnectedError/ClientPayloadError,
        which is caught here and treated as success. Only an immediate 4xx (e.g.
        empty/malformed body) on the SAME authenticated request is a real failure.
        This except clause is deliberately scoped to only the second (authenticated)
        POST - do not widen it to the challenge request or to request-writing.
        """
        url = f"{self.base_url}{path_and_query}"
        async with self._lock:
            try:
                try:
                    async with self._session.post(
                        url, data=b"", timeout=aiohttp.ClientTimeout(total=5)
                    ) as r1:
                        if r1.status != 401:
                            _LOGGER.warning(
                                "[_digest_post] Expected 401, got %s: %s", r1.status, url
                            )
                            return False
                        www_auth = r1.headers.get("WWW-Authenticate", "")
                except aiohttp.ClientConnectorError as err:
                    _LOGGER.error("[_digest_post] Connection refused: %s → %s", url, err)
                    return False
                except aiohttp.ServerTimeoutError:
                    _LOGGER.error("[_digest_post] Timeout (step1): %s", url)
                    return False

                if not www_auth:
                    _LOGGER.error("[_digest_post] 401 nhưng không có WWW-Authenticate: %s", url)
                    return False

                parsed = urlparse(url)
                uri = parsed.path + ("?" + parsed.query if parsed.query else "")
                try:
                    auth_header = self._build_digest_header("POST", uri, www_auth)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("[_digest_post] Tính Digest hash lỗi: %s", err)
                    return False

                try:
                    async with self._session.post(
                        url,
                        data=body,
                        headers={"Authorization": auth_header, "Content-Type": content_type},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as r2:
                        if r2.status == 200:
                            return True
                        _LOGGER.warning("[_digest_post] HTTP %s: %s", r2.status, await r2.text())
                        return False
                except (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError):
                    _LOGGER.debug(
                        "[_digest_post] Stream sent (%d bytes), no ack (bình thường với Dahua)",
                        len(body),
                    )
                    return True
                except aiohttp.ServerTimeoutError:
                    _LOGGER.error("[_digest_post] Timeout (step2): %s", url)
                    return False
                except aiohttp.ClientConnectorError as err:
                    _LOGGER.error("[_digest_post] Connection error (step2): %s", err)
                    return False
            except Exception as err:  # noqa: BLE001 - mirrors original catch-all
                _LOGGER.error(
                    "[_digest_post] Unexpected error: %s → %s: %s", url, type(err).__name__, err
                )
                return False

    async def _set_config_field(self, index_path: str, field: str, value) -> bool:
        """Write one configManager.cgi field and verify via readback.

        This device returns HTTP 400 for EVERY setConfig call regardless of
        whether the write actually succeeded (verified by reading the value
        back immediately after) - so the write's HTTP status is ignored
        entirely and only the readback result is trusted.
        """
        set_path = (
            f"/cgi-bin/configManager.cgi?action=setConfig&name={index_path}"
            f"&{index_path}.{field}={value}"
        )
        await self._digest_get(set_path)

        table_name = index_path.split("[")[0]
        status, body = await self._digest_get(
            f"/cgi-bin/configManager.cgi?action=getConfig&name={table_name}"
        )
        if status != 200:
            return False
        ok = f"{index_path}.{field}={value}" in body
        _LOGGER.debug(
            "[_set_config_field] %s.%s=%s → readback %s (setConfig HTTP luôn trả 400 trên "
            "thiết bị này dù ghi thành công, đã bỏ qua status code)",
            index_path,
            field,
            value,
            "OK" if ok else "FAILED",
        )
        return ok

    # ─────────────────────────────────────────────────
    # Connectivity / auth check (used by config_flow.validate_input)
    # ─────────────────────────────────────────────────
    async def async_test_connection(self) -> None:
        """Raise DahuaConnectionError/DahuaAuthError if setup should fail."""
        status, _ = await self._digest_get("/cgi-bin/devAudioOutput.cgi?action=getCollect")
        if status == -1:
            raise DahuaConnectionError(f"Cannot reach {self._host}:{self._port}")
        if status == 401:
            raise DahuaAuthError("Invalid username/password")
        if status != 200:
            raise DahuaConnectionError(f"Unexpected HTTP {status} from camera")

    # ─────────────────────────────────────────────────
    # PTZ movement
    # ─────────────────────────────────────────────────
    async def _cgi(self, action: str, code: str, speed: int = 0) -> bool:
        arg2 = speed if action == "start" else 0
        path = (
            f"/cgi-bin/ptz.cgi?action={action}&channel={self._channel}"
            f"&code={code}&arg1=0&arg2={arg2}&arg3=0"
        )
        status, _ = await self._digest_get(path)
        ok = status == 200
        if not ok:
            _LOGGER.warning("CGI %s %s → HTTP %s", action, code, status)
        return ok

    async def ptz_continuous_start(self, direction: str, speed: int) -> bool:
        code = DIRECTION_MAP.get(str(direction).lower())
        if not code:
            _LOGGER.error("Unknown direction '%s'", direction)
            return False
        return await self._cgi("start", code, max(1, min(8, int(speed))))

    async def ptz_continuous_stop(self, direction: str) -> bool:
        code = DIRECTION_MAP.get(str(direction).lower())
        if not code:
            _LOGGER.error("Unknown direction '%s'", direction)
            return False
        return await self._cgi("stop", code)

    async def ptz_move(self, direction: str, steps: int, speed: int, duration: float) -> None:
        """Step-move: start -> sleep -> stop, repeated `steps` times."""
        code = DIRECTION_MAP.get(str(direction).lower())
        if not code:
            _LOGGER.error("Unknown direction '%s'", direction)
            return

        steps = max(1, int(steps))
        speed = max(1, min(8, int(speed)))
        duration = max(0.05, float(duration))

        for i in range(steps):
            await self._cgi("start", code, speed)
            await asyncio.sleep(duration)
            await self._cgi("stop", code)
            if i < steps - 1:
                await asyncio.sleep(0.3)

    async def ptz_stop_all(self) -> None:
        """Send stop for every known PTZ code, to guarantee a full halt
        regardless of which direction might be mid-motion.
        """
        for code in set(DIRECTION_MAP.values()):
            await self._cgi("stop", code)

    # ─────────────────────────────────────────────────
    # Presets
    # ─────────────────────────────────────────────────
    async def fetch_presets(self) -> list[Preset]:
        status, body = await self._digest_get(
            f"/cgi-bin/ptz.cgi?action=getPresets&channel={self._channel}"
        )
        if status != 200:
            _LOGGER.error("getPresets HTTP %s", status)
            return []

        raw: dict[int, dict[str, str]] = {}
        for line in body.strip().replace("\r\n", "\n").split("\n"):
            line = line.strip()
            if not line or "presets[" not in line or "=" not in line:
                continue
            try:
                key, val = line.split("=", 1)
                idx = int(key.split("[")[1].split("]")[0])
                field_name = key.split(".")[-1]
                raw.setdefault(idx, {})[field_name] = val.strip()
            except Exception as err:  # noqa: BLE001 - mirrors original defensive parsing
                _LOGGER.warning("Parse preset line lỗi: '%s' → %s", line, err)
                continue

        presets: list[Preset] = []
        for i, p in sorted(raw.items()):
            name = p.get("Name", "").strip()
            if not name:
                continue
            try:
                presets.append(Preset(name=name, index=int(p.get("Index", i + 1))))
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Parse Index lỗi cho '%s': %s", name, err)
        return presets

    async def goto_preset(self, preset_no: int) -> bool:
        path = (
            f"/cgi-bin/ptz.cgi?action=start&channel={self._channel}"
            f"&code=GotoPreset&arg1=0&arg2={int(preset_no)}&arg3=0"
        )
        status, _ = await self._digest_get(path)
        return status == 200

    async def goto_preset_by_name(self, name: str, presets: list[Preset]) -> bool:
        match = next((p for p in presets if p.name == name), None)
        if match is None:
            _LOGGER.error("Preset '%s' không tìm thấy", name)
            return False
        return await self.goto_preset(match.index)

    async def set_preset(self, name: str, presets: list[Preset]) -> Preset | None:
        """Save the current position as a preset: overwrite by name if it
        already exists, else claim the lowest free slot (1-255).
        """
        name = str(name).strip()
        if not name:
            _LOGGER.error("preset name không được để trống")
            return None

        existing = {p.name: p.index for p in presets}
        if name in existing:
            preset_no = existing[name]
        else:
            used = set(existing.values())
            try:
                preset_no = next(i for i in range(1, 256) if i not in used)
            except StopIteration:
                _LOGGER.error("Không còn slot preset trống (max 255)")
                return None

        set_path = (
            f"/cgi-bin/ptz.cgi?action=start&channel={self._channel}"
            f"&code=SetPreset&arg1=0&arg2={preset_no}&arg3=0"
        )
        status, _ = await self._digest_get(set_path)
        if status != 200:
            _LOGGER.error("SetPreset HTTP %s", status)
            return None

        rename_path = (
            f"/cgi-bin/ptz.cgi?action=start&channel={self._channel}"
            f"&code=SetPresetName&arg1=0&arg2={preset_no}&arg3=0&name={name}"
        )
        r_status, _ = await self._digest_get(rename_path)
        if r_status != 200:
            _LOGGER.warning(
                "SetPresetName HTTP %s (firmware có thể không hỗ trợ đổi tên preset)", r_status
            )

        return Preset(name=name, index=preset_no)

    # ─────────────────────────────────────────────────
    # Audio / Speaker
    # ─────────────────────────────────────────────────
    async def probe_audio(self) -> AudioCapabilities:
        in_status, in_body = await self._digest_get(
            "/cgi-bin/devAudioInput.cgi?action=getCollect"
        )
        out_status, out_body = await self._digest_get(
            "/cgi-bin/devAudioOutput.cgi?action=getCollect"
        )

        def _parse_count(status: int, body: str) -> int:
            if status == 200 and "=" in body:
                try:
                    return int(body.strip().split("=")[-1])
                except ValueError:
                    return 0
            return 0

        return AudioCapabilities(
            input_channels=_parse_count(in_status, in_body),
            output_channels=_parse_count(out_status, out_body),
        )

    async def _post_alaw(self, alaw: bytes) -> bool:
        path = (
            f"/cgi-bin/audio.cgi?action=postAudioStream&HttpType=singlepart"
            f"&channel={self._channel}"
        )
        return await self._digest_post(path, alaw, "Audio/G.711A")

    async def play_tone(self, freq: float = 440.0, duration: float = 1.0) -> bool:
        """Play a one-shot sine tone through the speaker (beep test/alert)."""
        alaw = _gen_tone_alaw(float(freq), float(duration))
        return await self._post_alaw(alaw)

    async def play_media_bytes(self, alaw: bytes) -> bool:
        """POST already-alaw-encoded audio to the speaker.

        Callers (media_player.py) are responsible for decoding WAV/mp3 source
        bytes down to G.711 A-law before calling this - see
        `wav_bytes_to_alaw`/`pcm16_to_alaw` in this module for the WAV path.
        """
        return await self._post_alaw(alaw)

    # ─────────────────────────────────────────────────
    # Light / Active Deterrence
    # ─────────────────────────────────────────────────
    async def light_set(self, on: bool, level: int = 100) -> bool:
        level = max(0, min(100, int(level))) if on else 0
        ok_mode = await self._set_config_field(LIGHT_TABLE, "Mode", "Manual")
        ok_level = await self._set_config_field(LIGHT_TABLE, "NearLight[0].Light", level)
        return ok_mode and ok_level

    async def light_get_status(self) -> LightStatus:
        table_name = LIGHT_TABLE.split("[")[0]
        status, body = await self._digest_get(
            f"/cgi-bin/configManager.cgi?action=getConfig&name={table_name}"
        )
        if status != 200:
            _LOGGER.error("light_get_status HTTP %s", status)
            return LightStatus()

        prefix = f"table.{LIGHT_TABLE}."
        info = {
            line[len(prefix):].split("=", 1)[0]: line.split("=", 1)[1]
            for line in body.splitlines()
            if line.startswith(prefix)
        }
        mode = info.get("Mode")
        try:
            level = int(info.get("NearLight[0].Light", 0))
        except ValueError:
            level = 0
        return LightStatus(mode=mode, level=level)

    async def alarm_set(self, enable: bool) -> bool:
        value = "true" if enable else "false"
        return await self._set_config_field(ALARM_TABLE, "Enable", value)

    async def alarm_get_status(self) -> bool:
        table_name = ALARM_TABLE.split("[")[0]
        status, body = await self._digest_get(
            f"/cgi-bin/configManager.cgi?action=getConfig&name={table_name}"
        )
        if status != 200:
            _LOGGER.error("alarm_get_status HTTP %s", status)
            return False
        return f"{ALARM_TABLE}.Enable=true" in body
