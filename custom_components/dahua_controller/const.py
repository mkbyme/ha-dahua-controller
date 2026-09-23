"""Constants for the Dahua Controller integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "dahua_controller"

# ── Config entry keys ──────────────────────────────────────────────
CONF_CHANNEL = "channel"

DEFAULT_PORT = 80
DEFAULT_CHANNEL = 1
DEFAULT_NAME = "Dahua Camera"

# ── Options keys (non-credential, editable via OptionsFlow) ───────
CONF_PTZ_SPEED = "ptz_speed"
CONF_PTZ_DURATION = "ptz_duration"
CONF_PTZ_STEPS = "ptz_steps"

DEFAULT_SPEED = 3
DEFAULT_DURATION = 0.15
DEFAULT_STEPS = 1
DEFAULT_SCAN_INTERVAL = 60  # seconds; polls light + active-deterrence state only

# ── Config flow error/status vocabulary (also used as strings.json keys) ──
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_UNKNOWN = "unknown"

PLATFORMS = [
    Platform.SELECT,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.LIGHT,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
]

# ── PTZ direction → Dahua ptz.cgi code map ─────────────────────────
DIRECTION_MAP = {
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "zoom_in": "ZoomTele",
    "zoom_out": "ZoomWide",
}
# Directions exposed as button entities (Stop halts all of these, not just these four,
# to guarantee a full halt regardless of what's mid-motion).
BUTTON_DIRECTIONS = ("up", "down", "left", "right")

DEFAULT_TONE_FREQ = 440.0
DEFAULT_TONE_DURATION = 1.0

# ── Speaker output gain (applied to PCM16 samples before A-law encode) ─────
# Peak-normalize toward this fraction of full scale (±32767); boost-only, never
# attenuates already-loud audio. AUDIO_MAX_GAIN caps amplification so a
# near-silent buffer (noise floor, silence padding) doesn't get blown up.
AUDIO_TARGET_PEAK = 0.95
AUDIO_MAX_GAIN = 12.0

# ── Light / Active Deterrence config tables ────────────────────────
# Scanned via configManager.cgi getConfig/setConfig on the reference device
# (DH-P5D-5F-PV). Lighting[0][0]/Lighting[1][0] are the two light channels;
# Lighting[1][0] is an UNVERIFIED assumption that it is the visible white
# spotlight rather than the IR illuminator - confirmed only via config
# readback, not by observing the physical light. If light.<camera>_spotlight
# doesn't visibly do anything, flip this to "Lighting[0][0]" and reload.
LIGHT_TABLE = "Lighting[1][0]"
ALARM_TABLE = "LightGlobal[0]"

# ── EXPERIMENTAL: NetSDK (TCP 37777) config attempt for lighting ───────────
# The configManager.cgi write above (LIGHT_TABLE) is verified to persist -
# reading the config back confirms it - but was never confirmed to actually
# drive the physical light. That's the exact same "CGI accepts the request
# but does nothing on real hardware" pattern already hit and fixed for
# audio.cgi (see the DahuaNetSDKTalk docstring in dahua_client.py), so
# light_set() also fires this as a best-effort NetSDK attempt alongside the
# CGI write. UNVERIFIED GUESS: this ParameterName is extrapolated from the
# one NetSDK object this project has confirmed working
# ("Dahua.Device.Network.Talk.General") - there is no reference/capture for
# the correct lighting object name or even confirmation this RPC shape
# applies outside of Talk. Watch the HA log for "[NetSDK][light]" lines and
# report the raw response back so this can be corrected against your camera.
NETSDK_LIGHT_PARAM = "Dahua.Device.Lighting[1][0]"

# ── Speaker volume (see DahuaClient.speaker_volume_set) ────────────────────
# Initial value shown by the number.<camera>_speaker_volume entity. There is
# no way to read the camera's actual output level back, so this is just "the
# value we'll ask for" on the next playback, not a confirmed hardware state.
DEFAULT_SPEAKER_VOLUME = 100
