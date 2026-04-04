"""Config flow for the KC100 integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

from .client import KC100AuthError, KC100Client, KC100Error
from .const import (
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _validate(host: str, username: str, password: str) -> str | None:
    """Return an error key if validation fails, else None."""
    client = KC100Client(host, username, password)
    try:
        await client.get_led()
    except KC100AuthError:
        return ERROR_INVALID_AUTH
    except aiohttp.ClientError, TimeoutError, KC100Error:
        _LOGGER.debug("KC100 connection test failed for %s", host, exc_info=True)
        return ERROR_CANNOT_CONNECT
    except Exception:
        _LOGGER.exception("Unexpected KC100 validation error")
        return ERROR_UNKNOWN
    finally:
        await client.close()
    return None


class KC100ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the KC100 integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: host/username/password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            error = await _validate(
                host,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            if error is None:
                return self.async_create_entry(
                    title=f"KC100 ({host})",
                    data=user_input,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauth when credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for new credentials and update the entry."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        host = reauth_entry.data[CONF_HOST]

        if user_input is not None:
            error = await _validate(
                host,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={**reauth_entry.data, **user_input},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=reauth_entry.data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={"host": host},
        )
