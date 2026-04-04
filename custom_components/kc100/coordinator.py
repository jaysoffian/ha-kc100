"""Data update coordinator for the KC100 integration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    KC100AuthError,
    KC100Client,
    KC100Error,
    NightVisionMode,
    OnOff,
    Quality,
    Resolution,
    Sensitivity,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class KC100Data:
    """Snapshot of camera state returned by the coordinator."""

    power: OnOff | None = None
    led: OnOff | None = None
    motion_enabled: OnOff | None = None
    motion_sensitivity: Sensitivity | None = None
    sound_enabled: OnOff | None = None
    sound_sensitivity: Sensitivity | None = None
    resolution: Resolution | None = None
    quality: Quality | None = None
    rotation: int | None = None
    power_frequency: int | None = None
    night_vision: NightVisionMode | None = None
    cloud_info: dict[str, Any] | None = None


class KC100Coordinator(DataUpdateCoordinator[KC100Data]):
    """Poll a KC100 camera for its current state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: KC100Client,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data.get(CONF_HOST, entry.entry_id)}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.entry = entry
        self._last_field_ok: dict[str, bool] = {}
        # Our own copy of the last returned snapshot, so we can merge in
        # previously-known values when a getter fails this round.
        # ``self.data`` is typed ``KC100Data`` by the base class and can't be
        # used as ``KC100Data | None`` here.
        self._last: KC100Data | None = None

    async def _async_update_data(self) -> KC100Data:
        """Fetch the current state from the camera.

        The KC100 resets concurrent SSL handshakes, so getters run one at
        a time (the connector's ``limit_per_host=1`` already serializes on
        the wire, but we do not rely on that). A single getter tripping
        on a transient error does not lose all fields. Auth failures
        escalate immediately; if fewer than half the fields succeed we
        raise ``UpdateFailed``.
        """
        client = self.client
        getters: list[tuple[str, Callable[[], Awaitable[Any]]]] = [
            ("power", client.get_power),
            ("led", client.get_led),
            ("motion_enabled", client.get_motion_enabled),
            ("motion_sensitivity", client.get_motion_sensitivity),
            ("sound_enabled", client.get_sound_enabled),
            ("sound_sensitivity", client.get_sound_sensitivity),
            ("resolution", client.get_resolution),
            ("quality", client.get_channel_quality),
            ("rotation", client.get_rotation),
            ("power_frequency", client.get_power_frequency),
            ("night_vision", client.get_night_vision),
            ("cloud_info", client.get_cloud_info),
        ]

        values: dict[str, Any] = {}
        errors: list[BaseException] = []
        for name, factory in getters:
            try:
                values[name] = await factory()
            except KC100AuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except (aiohttp.ClientError, TimeoutError, KC100Error) as err:
                errors.append(err)
                prev_ok = self._last_field_ok.get(name, True)
                if prev_ok:
                    _LOGGER.warning("getter %s failed: %s", name, err)
                else:
                    _LOGGER.debug("getter %s failed: %s", name, err)
                self._last_field_ok[name] = False
            else:
                prev_ok = self._last_field_ok.get(name, True)
                if not prev_ok:
                    _LOGGER.info("getter %s recovered", name)
                self._last_field_ok[name] = True

        # If we lost more than half the fields, treat the whole update as
        # failed rather than hand HA a mostly-empty snapshot.
        if len(values) * 2 < len(getters):
            err = errors[0]
            _LOGGER.warning(
                "update failed: %d/%d getters errored: %s",
                len(errors),
                len(getters),
                "; ".join(f"{type(e).__name__}: {e}" for e in errors),
            )
            raise UpdateFailed(f"{type(err).__name__}: {err}") from err

        # Preserve previously-known values for fields that failed this round.
        prev = self._last
        if prev is not None:
            for name, _ in getters:
                if name not in values:
                    values[name] = getattr(prev, name)
        result = KC100Data(**values)
        self._last = result
        return result

    async def async_refresh_after_set(self) -> None:
        """Trigger an immediate refresh after a set command."""
        await self.async_request_refresh()
