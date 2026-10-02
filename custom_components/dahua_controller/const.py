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
CONF_AUDIO_MAX_GAIN = "audio_max_gain"  # percent, 100-150

DEFAULT_SPEED = 3
DEFAULT_DURATION = 0.15
DEFAULT_STEPS = 1
DEFAULT_AUDIO_GAIN = 100
MIN_AUDIO_GAIN = 100
MAX_AUDIO_GAIN = 150
DEFAULT_SCAN_INTERVAL = 60  # seconds; polls active-deterrence state only

# ── Config flow error/status vocabulary (also used as strings.json keys) ──
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_UNKNOWN = "unknown"

PLATFORMS = [
    Platform.SELECT,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.MEDIA_PLAYER,
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
# attenuates already-loud audio. AUDIO_BOOST_LIMIT caps that automatic boost so a
# near-silent buffer (noise floor, silence padding) doesn't get blown up. The
# user-facing CONF_AUDIO_MAX_GAIN option (100-150 %) scales on top of it.
AUDIO_TARGET_PEAK = 0.95
AUDIO_BOOST_LIMIT = 12.0

# ── Active Deterrence config table ─────────────────────────────────
ALARM_TABLE = "LightGlobal[0]"
