"""Shared base entity for the Dahua Controller integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DahuaCoordinator


class DahuaControllerEntity(CoordinatorEntity[DahuaCoordinator]):
    """Base entity: wires up the shared DeviceInfo for one camera.

    Every platform entity for a given config entry attaches this same
    DeviceInfo (keyed off the entry's unique_id, i.e. host:port:channel) so
    they all group under a single HA device per camera.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: DahuaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        host = entry.data[CONF_HOST]
        port = entry.data[CONF_PORT]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.data.get(CONF_NAME, "Dahua Camera"),
            manufacturer="Dahua",
            model="PTZ Camera",
            configuration_url=f"http://{host}:{port}",
        )
