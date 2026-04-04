"""Base entity for the KC100 integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import KC100Coordinator


class KC100Entity(CoordinatorEntity[KC100Coordinator]):
    """Base class for KC100 entities: shared device info."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KC100Coordinator) -> None:
        super().__init__(coordinator)
        host = coordinator.entry.data[CONF_HOST]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=f"https://{host}:10443",
        )
