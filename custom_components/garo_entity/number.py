# pyright: reportMissingImports=false

"""Number platform for Garo Entity integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import GaroEntityAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Configuration keys that should have number controls
CONFIGURABLE_NUMBERS = {
    "GaroOwnerMaxCurrent": {
        "name": "Max Current (Owner)",
        "icon": "mdi:current-ac",
        "unit": "A",
        "min": 6.0,
        "max": 32.0,
        "step": 1.0,
        "mode": NumberMode.SLIDER,
    },
    "LightIntensity": {
        "name": "Light Intensity",
        "icon": "mdi:brightness-6", 
        "unit": "%",
        "min": 0.0,
        "max": 100.0,
        "step": 1.0,
        "mode": NumberMode.SLIDER,
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Garo Entity number entities."""
    api: GaroEntityAPI = hass.data[DOMAIN][config_entry.entry_id]
    
    # Import here to avoid circular imports
    from .sensor import GaroEntityDataUpdateCoordinator
    
    # Create coordinator for this platform
    coordinator = GaroEntityDataUpdateCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()
    
    entities = []
    
    # Create number entities for configurable values
    configurations_data = coordinator.data.get("configurations", {})
    
    for station_id, station_data in configurations_data.items():
        station_info = station_data.get("station_info", {})
        configuration = station_data.get("configuration", [])
        
        if isinstance(configuration, list):
            for config_item in configuration:
                key = config_item.get("key")
                value = config_item.get("value")
                
                # Only create number entities for supported configuration keys
                if key in CONFIGURABLE_NUMBERS and value is not None:
                    entities.append(
                        GaroEntityConfigurationNumber(
                            coordinator,
                            api,
                            config_entry,
                            station_id,
                            station_info,
                            key,
                            config_item
                        )
                    )
                    _LOGGER.debug("Created number entity for %s %s", 
                                station_info.get("name", station_id[:8]), key)
    
    if entities:
        async_add_entities(entities)
        _LOGGER.info("Created %s number entities for Garo Entity integration", len(entities))


class GaroEntityConfigurationNumber(CoordinatorEntity, NumberEntity):
    """Number entity for configuration values that can be changed."""

    def __init__(
        self,
        coordinator,
        api: GaroEntityAPI,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        config_key: str,
        config_item: dict[str, Any],
    ) -> None:
        """Initialize the configuration number entity."""
        super().__init__(coordinator)
        
        self.api = api
        self.station_id = station_id
        self.station_info = station_info
        self.config_key = config_key
        self.config_item = config_item
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        config_info = CONFIGURABLE_NUMBERS[config_key]
        
        # Set entity attributes
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_number_{config_key.lower()}"
        self._attr_name = f"{station_name} {config_info['name']}"
        self._attr_icon = config_info["icon"]
        self._attr_native_unit_of_measurement = config_info["unit"]
        self._attr_native_min_value = config_info["min"]
        self._attr_native_max_value = config_info["max"]
        self._attr_native_step = config_info["step"]
        self._attr_mode = config_info["mode"]

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not self.coordinator.data:
            return None
            
        configurations_data = self.coordinator.data.get("configurations", {})
        station_data = configurations_data.get(self.station_id)
        
        if not station_data:
            return None
            
        configuration = station_data.get("configuration", [])
        if not isinstance(configuration, list):
            return None
        
        # Find the configuration item with matching key
        for config_item in configuration:
            if config_item.get("key") == self.config_key:
                value = config_item.get("value")
                if value is not None:
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        _LOGGER.warning("Could not convert config value to float: %s", value)
                        return None
        
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the configuration value."""
        try:
            _LOGGER.info("Setting %s to %s for station %s", 
                        self.config_key, value, self.station_info.get("name", self.station_id))
            
            # Convert float to int for current values, keep as float for percentages
            if "Current" in self.config_key:
                api_value = int(value)
            else:
                api_value = value
                
            await self.api.set_charging_station_configuration(
                self.station_id,
                self.config_key, 
                api_value
            )
            
            # Request a refresh to update the sensor values
            await self.coordinator.async_request_refresh()
            
        except Exception as exc:
            _LOGGER.error("Failed to set %s to %s: %s", self.config_key, value, exc)
            raise

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return None
            
        configurations_data = self.coordinator.data.get("configurations", {})
        station_data = configurations_data.get(self.station_id)
        
        if not station_data:
            return None
            
        # Find the configuration item for additional attributes
        configuration = station_data.get("configuration", [])
        if isinstance(configuration, list):
            for config_item in configuration:
                if config_item.get("key") == self.config_key:
                    return {
                        "station_name": self.station_info.get("name"),
                        "station_uid": self.station_info.get("uid"),
                        "charging_station_id": self.station_id,
                        "config_key": self.config_key,
                        "last_modified": config_item.get("last_modified"),
                        "last_synced_with_charging_station": config_item.get("last_synced_with_charging_station"),
                        "status": config_item.get("status"),
                    }
        
        return {
            "station_name": self.station_info.get("name"),
            "station_uid": self.station_info.get("uid"), 
            "charging_station_id": self.station_id,
            "config_key": self.config_key,
        }