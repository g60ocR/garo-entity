"""The Garo Entity integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .api import GaroEntityAPI
from .const import (
    DOMAIN,
    CONF_COGNITO_CLIENT_ID,
    CONF_COGNITO_REGION,
    CONF_API_BASE_URL,
    DEFAULT_COGNITO_CLIENT_ID,
    DEFAULT_COGNITO_REGION,
    DEFAULT_API_BASE_URL,
)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Garo Entity from a config entry."""
    api = GaroEntityAPI(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        cognito_client_id=entry.data.get(CONF_COGNITO_CLIENT_ID, DEFAULT_COGNITO_CLIENT_ID),
        cognito_region=entry.data.get(CONF_COGNITO_REGION, DEFAULT_COGNITO_REGION),
        api_base_url=entry.data.get(CONF_API_BASE_URL, DEFAULT_API_BASE_URL),
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = api

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok