"""Sensor platform for the KC100 integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import KC100ConfigEntry
from .coordinator import KC100Coordinator, KC100Data
from .entity import KC100Entity


@dataclass(frozen=True, kw_only=True)
class KC100SensorEntityDescription(SensorEntityDescription):
    """Describes a KC100 sensor entity."""

    value_fn: Callable[[KC100Data], StateType]
    attrs_fn: Callable[[KC100Data], dict[str, Any] | None] | None = None


def _cloud_status(data: KC100Data) -> StateType:
    info = data.cloud_info
    if info is None:
        return None
    return "connected" if info.get("cld_connection") else "disconnected"


def _cloud_attrs(data: KC100Data) -> dict[str, Any] | None:
    info = data.cloud_info
    if not info:
        return None
    return {k: v for k, v in info.items() if k != "err_code"}


SENSOR_ENTITIES: tuple[KC100SensorEntityDescription, ...] = (
    KC100SensorEntityDescription(
        key="resolution",
        translation_key="resolution_sensor",
        icon="mdi:quality-high",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.resolution,
    ),
    KC100SensorEntityDescription(
        key="quality",
        translation_key="quality_sensor",
        icon="mdi:video-high-definition",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.quality,
    ),
    KC100SensorEntityDescription(
        key="night_vision",
        translation_key="night_vision_sensor",
        icon="mdi:weather-night",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.night_vision,
    ),
    KC100SensorEntityDescription(
        key="cloud_status",
        translation_key="cloud_status",
        icon="mdi:cloud",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_cloud_status,
        attrs_fn=_cloud_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KC100ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KC100 sensor entities."""
    coordinator = entry.runtime_data
    async_add_entities(KC100SensorEntity(coordinator, desc) for desc in SENSOR_ENTITIES)


class KC100SensorEntity(KC100Entity, SensorEntity):
    """A KC100 diagnostic sensor."""

    entity_description: KC100SensorEntityDescription

    def __init__(
        self,
        coordinator: KC100Coordinator,
        description: KC100SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
