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

# ── Light / Active Deterrence config tables ────────────────────────
# Scanned via configManager.cgi getConfig/setConfig on the reference device
# (DH-P5D-5F-PV). Lighting[0][0]/Lighting[1][0] are the two light channels;
# Lighting[1][0] is an UNVERIFIED assumption that it is the visible white
# spotlight rather than the IR illuminator - confirmed only via config
# readback, not by observing the physical light. If light.<camera>_spotlight
# doesn't visibly do anything, flip this to "Lighting[0][0]" and reload.
LIGHT_TABLE = "Lighting[1][0]"
ALARM_TABLE = "LightGlobal[0]"
