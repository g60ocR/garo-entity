# pyright: reportMissingImports=false

"""Config flow for Garo Entity integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    CONF_COGNITO_CLIENT_ID,
    CONF_COGNITO_REGION,
    CONF_API_BASE_URL,
    DEFAULT_COGNITO_CLIENT_ID,
    DEFAULT_COGNITO_REGION,
    DEFAULT_API_BASE_URL,
)
from .api import GaroEntityAPI

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_COGNITO_CLIENT_ID, default=DEFAULT_COGNITO_CLIENT_ID): str,
        vol.Optional(CONF_COGNITO_REGION, default=DEFAULT_COGNITO_REGION): str,
        vol.Optional(CONF_API_BASE_URL, default=DEFAULT_API_BASE_URL): str,
    }
)

STEP_ADVANCED_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_COGNITO_CLIENT_ID, default=DEFAULT_COGNITO_CLIENT_ID): str,
        vol.Optional(CONF_COGNITO_REGION, default=DEFAULT_COGNITO_REGION): str,
        vol.Optional(CONF_API_BASE_URL, default=DEFAULT_API_BASE_URL): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Garo Entity."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    api = GaroEntityAPI(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        cognito_client_id=data.get(CONF_COGNITO_CLIENT_ID, DEFAULT_COGNITO_CLIENT_ID),
        cognito_region=data.get(CONF_COGNITO_REGION, DEFAULT_COGNITO_REGION),
        api_base_url=data.get(CONF_API_BASE_URL, DEFAULT_API_BASE_URL),
    )

    try:
        await api.test_connection()
    except Exception as exc:
        if "401" in str(exc) or "Unauthorized" in str(exc) or "InvalidParameterException" in str(exc):
            raise InvalidAuth from exc
        raise CannotConnect from exc

    return {"title": f"Garo Entity ({data[CONF_USERNAME]})"}


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""