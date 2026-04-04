"""Switch platform for the KC100 integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KC100ConfigEntry
from .client import KC100Client, OnOff
from .coordinator import KC100Coordinator, KC100Data
from .entity import KC100Entity


@dataclass(frozen=True, kw_only=True)
class KC100SwitchEntityDescription(SwitchEntityDescription):
    """Describes a KC100 switch entity."""

    is_on_fn: Callable[[KC100Data], OnOff | None]
    set_fn: Callable[[KC100Client, OnOff], Awaitable[None]]


SWITCH_ENTITIES: tuple[KC100SwitchEntityDescription, ...] = (
    KC100SwitchEntityDescription(
        key="power",
        translation_key="power",
        icon="mdi:cctv",
        is_on_fn=lambda d: d.power,
        set_fn=lambda c, v: c.set_power(v),
    ),
    KC100SwitchEntityDescription(
        key="led",
        translation_key="led",
        icon="mdi:led-on",
        is_on_fn=lambda d: d.led,
        set_fn=lambda c, v: c.set_led(v),
    ),
    KC100SwitchEntityDescription(
        key="motion_detect",
        translation_key="motion_detect",
        icon="mdi:motion-sensor",
        is_on_fn=lambda d: d.motion_enabled,
        set_fn=lambda c, v: c.set_motion_enabled(v),
    ),
    KC100SwitchEntityDescription(
        key="sound_detect",
        translation_key="sound_detect",
        icon="mdi:microphone",
        is_on_fn=lambda d: d.sound_enabled,
        set_fn=lambda c, v: c.set_sound_enabled(v),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KC100ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KC100 switch entities."""
    coordinator = entry.runtime_data
    async_add_entities(KC100SwitchEntity(coordinator, desc) for desc in SWITCH_ENTITIES)


class KC100SwitchEntity(KC100Entity, SwitchEntity):
    """A KC100 switch entity."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    entity_description: KC100SwitchEntityDescription

    def __init__(
        self,
        coordinator: KC100Coordinator,
        description: KC100SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        value = self.entity_description.is_on_fn(self.coordinator.data)
        if value is None:
            return None
        return value == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.entity_description.set_fn(self.coordinator.client, "on")
        await self.coordinator.async_refresh_after_set()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.entity_description.set_fn(self.coordinator.client, "off")
        await self.coordinator.async_refresh_after_set()
