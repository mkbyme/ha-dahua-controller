"""Config flow for the Dahua Controller integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_CHANNEL,
    CONF_PTZ_DURATION,
    CONF_PTZ_SPEED,
    CONF_PTZ_STEPS,
    DEFAULT_CHANNEL,
    DEFAULT_DURATION,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SPEED,
    DEFAULT_STEPS,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
)
from .dahua_client import DahuaAuthError, DahuaClient, DahuaConnectionError

_LOGGER = logging.getLogger(__name__)


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST)): str,
            vol.Optional(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME)): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD)): str,
            vol.Optional(
                CONF_CHANNEL, default=defaults.get(CONF_CHANNEL, DEFAULT_CHANNEL)
            ): int,
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
        }
    )


async def validate_input(hass, data: dict[str, Any]) -> None:
    """Attempt a lightweight authenticated call against the camera.

    Raises DahuaConnectionError / DahuaAuthError on failure; returns None on
    success. Uses a throwaway client, not the entry's shared client.
    """
    client = DahuaClient(
        hass,
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        channel=data[CONF_CHANNEL],
    )
    await client.async_test_connection()


class DahuaControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dahua Controller."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "OptionsFlowHandler":
        return OptionsFlowHandler(config_entry)

    async def _validate_and_build_result(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Returns (errors, data). errors is empty dict on success."""
        errors: dict[str, str] = {}
        try:
            await validate_input(self.hass, user_input)
        except DahuaAuthError:
            errors["base"] = ERROR_INVALID_AUTH
        except DahuaConnectionError:
            errors["base"] = ERROR_CANNOT_CONNECT
        except Exception:  # noqa: BLE001 - guard against any unexpected failure
            _LOGGER.exception("Unexpected error validating Dahua camera connection")
            errors["base"] = ERROR_UNKNOWN
        return errors, user_input

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors, user_input = await self._validate_and_build_result(user_input)
            if not errors:
                unique_id = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:{user_input[CONF_CHANNEL]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME), data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow editing host/port/username/password/channel/name after setup."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors, user_input = await self._validate_and_build_result(user_input)
            if not errors:
                # unique_id is derived from host:port:channel, which is exactly what
                # this flow lets the user edit (e.g. camera got a new static IP) - so
                # it must be re-set here rather than checked with
                # _abort_if_unique_id_mismatch, which would abort on every host/port/
                # channel edit and silently leave entry.data unchanged.
                new_unique_id = (
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:{user_input[CONF_CHANNEL]}"
                )
                await self.async_set_unique_id(new_unique_id)
                return self.async_update_reload_and_abort(entry, data=user_input)

        schema = self.add_suggested_values_to_schema(_schema(), entry.data)
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Non-credential per-camera tunables: PTZ step speed/duration/steps and
    the coordinator's poll interval. Credentials are edited via the
    reconfigure flow, not here, to avoid the two flows racing.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_PTZ_SPEED, default=options.get(CONF_PTZ_SPEED, DEFAULT_SPEED)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
                vol.Optional(
                    CONF_PTZ_DURATION, default=options.get(CONF_PTZ_DURATION, DEFAULT_DURATION)
                ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=5)),
                vol.Optional(
                    CONF_PTZ_STEPS, default=options.get(CONF_PTZ_STEPS, DEFAULT_STEPS)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=3600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
