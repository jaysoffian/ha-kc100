"""TP-Link Kasa KC100 integration."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .client import KC100Client
from .const import PLATFORMS
from .coordinator import KC100Coordinator

_LOGGER = logging.getLogger(__name__)

type KC100ConfigEntry = ConfigEntry[KC100Coordinator]


async def async_setup_entry(hass: HomeAssistant, entry: KC100ConfigEntry) -> bool:
    """Set up a KC100 config entry."""
    client = KC100Client(
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = KC100Coordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KC100ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        try:
            await entry.runtime_data.client.close()
        except (aiohttp.ClientError, OSError) as err:
            _LOGGER.warning("error closing KC100 client: %s", err)
    return unload_ok
