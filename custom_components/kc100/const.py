"""Constants for the KC100 integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "kc100"

PLATFORMS: list[Platform] = [
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)

MANUFACTURER = "TP-Link"
MODEL = "KC100"

ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_UNKNOWN = "unknown"
