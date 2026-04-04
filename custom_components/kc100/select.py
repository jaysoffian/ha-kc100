"""Select platform for the KC100 integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KC100ConfigEntry
from .client import (
    KC100Client,
    NightVisionMode,
    PowerFreq,
    Quality,
    Resolution,
    Rotation,
    Sensitivity,
)
from .coordinator import KC100Coordinator, KC100Data
from .entity import KC100Entity


@dataclass(frozen=True, kw_only=True)
class KC100SelectEntityDescription(SelectEntityDescription):
    """Describes a KC100 select entity."""

    current_fn: Callable[[KC100Data], str | None]
    select_fn: Callable[[KC100Client, str], Awaitable[None]]


RESOLUTION_OPTIONS: list[str] = ["1080P", "720P", "360P"]
QUALITY_OPTIONS: list[str] = ["low", "medium", "high"]
SENSITIVITY_OPTIONS: list[str] = ["low", "medium", "high"]
NIGHT_VISION_OPTIONS: list[str] = ["auto", "day", "night"]
ROTATION_OPTIONS: list[str] = ["0", "180"]
POWER_FREQ_OPTIONS: list[str] = ["50", "60"]


def _str_or_none(value: object) -> str | None:
    return None if value is None else str(value)


SELECT_ENTITIES: tuple[KC100SelectEntityDescription, ...] = (
    KC100SelectEntityDescription(
        key="resolution",
        translation_key="resolution",
        icon="mdi:quality-high",
        options=RESOLUTION_OPTIONS,
        current_fn=lambda d: d.resolution,
        select_fn=lambda c, v: c.set_resolution(cast("Resolution", v)),
    ),
    KC100SelectEntityDescription(
        key="quality",
        translation_key="quality",
        icon="mdi:video-high-definition",
        options=QUALITY_OPTIONS,
        current_fn=lambda d: d.quality,
        select_fn=lambda c, v: c.set_channel_quality(cast("Quality", v)),
    ),
    KC100SelectEntityDescription(
        key="night_vision",
        translation_key="night_vision",
        icon="mdi:weather-night",
        options=NIGHT_VISION_OPTIONS,
        current_fn=lambda d: d.night_vision,
        select_fn=lambda c, v: c.set_night_vision(cast("NightVisionMode", v)),
    ),
    KC100SelectEntityDescription(
        key="motion_sensitivity",
        translation_key="motion_sensitivity",
        icon="mdi:motion-sensor",
        options=SENSITIVITY_OPTIONS,
        current_fn=lambda d: d.motion_sensitivity,
        select_fn=lambda c, v: c.set_motion_sensitivity(cast("Sensitivity", v)),
    ),
    KC100SelectEntityDescription(
        key="sound_sensitivity",
        translation_key="sound_sensitivity",
        icon="mdi:microphone",
        options=SENSITIVITY_OPTIONS,
        current_fn=lambda d: d.sound_sensitivity,
        select_fn=lambda c, v: c.set_sound_sensitivity(cast("Sensitivity", v)),
    ),
    KC100SelectEntityDescription(
        key="rotation",
        translation_key="rotation",
        icon="mdi:rotate-right",
        options=ROTATION_OPTIONS,
        current_fn=lambda d: _str_or_none(d.rotation),
        select_fn=lambda c, v: c.set_rotation(cast("Rotation", int(v))),
    ),
    KC100SelectEntityDescription(
        key="power_frequency",
        translation_key="power_frequency",
        icon="mdi:sine-wave",
        options=POWER_FREQ_OPTIONS,
        current_fn=lambda d: _str_or_none(d.power_frequency),
        select_fn=lambda c, v: c.set_power_frequency(cast("PowerFreq", int(v))),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KC100ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KC100 select entities."""
    coordinator = entry.runtime_data
    async_add_entities(KC100SelectEntity(coordinator, desc) for desc in SELECT_ENTITIES)


class KC100SelectEntity(KC100Entity, SelectEntity):
    """A KC100 select entity."""

    entity_description: KC100SelectEntityDescription

    def __init__(
        self,
        coordinator: KC100Coordinator,
        description: KC100SelectEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        if description.options is None:
            raise ValueError(f"options required for {description.key}")
        self._attr_options = description.options

    @property
    def current_option(self) -> str | None:
        value = self.entity_description.current_fn(self.coordinator.data)
        if value is None or value not in self._attr_options:
            return None
        return value

    async def async_select_option(self, option: str) -> None:
        await self.entity_description.select_fn(self.coordinator.client, option)
        await self.coordinator.async_refresh_after_set()
