# pyright: reportMissingImports=false

"""Sensor platform for Garo Entity integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import GaroEntityAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Garo Entity sensors."""
    api: GaroEntityAPI = hass.data[DOMAIN][config_entry.entry_id]

    coordinator = GaroEntityDataUpdateCoordinator(hass, api)
    
    # Always add the count sensor first
    entities = [
        GaroEntityChargingStationsCountSensor(coordinator, config_entry),
    ]
    
    try:
        # Do initial refresh but don't block on meter values if they fail
        await coordinator.async_config_entry_first_refresh()
        
        # Create meter value sensors for each charging station and meter type
        meter_values_data = coordinator.data.get("meter_values", {})
        _LOGGER.debug("Setting up meter value sensors for %s stations", len(meter_values_data))
        
        for station_id, station_data in meter_values_data.items():
            station_info = station_data.get("station_info", {})
            meter_values = station_data.get("meter_values", {})
            
            if isinstance(meter_values, list):
                # Group meter values by measure_name + phase to create one sensor per meter type and phase
                meter_types = {}
                for item in meter_values:
                    measure_name = item.get("measure_name")
                    phase = item.get("phase")
                    location = item.get("location")
                    
                    if measure_name:
                        # Create unique key including phase and location for differentiation
                        key_parts = [measure_name]
                        if phase:
                            key_parts.append(f"phase_{phase}")
                        if location:
                            key_parts.append(f"loc_{location}")
                        
                        unique_key = "_".join(key_parts)
                        
                        # Get the most recent value for each unique meter type/phase combination
                        if unique_key not in meter_types or item.get("time", "") > meter_types[unique_key].get("time", ""):
                            meter_types[unique_key] = item
                
                _LOGGER.debug("Creating %s meter sensors for station %s", 
                            len(meter_types), station_info.get("name", station_id[:8]))
                
                # Create a sensor for each unique meter type/phase combination
                for unique_key, meter_data in meter_types.items():
                    entities.append(
                        GaroEntityMeterValueSensor(
                            coordinator, 
                            config_entry, 
                            station_id, 
                            station_info,
                            unique_key, 
                            meter_data
                        )
                    )

        # Create connector status sensors for each charging station
        connector_statuses_data = coordinator.data.get("connector_statuses", {})
        _LOGGER.debug("Setting up connector status sensors for %s stations", len(connector_statuses_data))
        
        for station_id, station_data in connector_statuses_data.items():
            station_info = station_data.get("station_info", {})
            connector_status = station_data.get("connector_status", [])
            
            if isinstance(connector_status, list):
                # Find connector ID 1 status
                for connector in connector_status:
                    if connector.get("connector_id") == 1:
                        entities.append(
                            GaroEntityConnectorStatusSensor(
                                coordinator,
                                config_entry,
                                station_id,
                                station_info,
                                connector
                            )
                        )
                        _LOGGER.debug("Created connector status sensor for station %s connector 1", 
                                    station_info.get("name", station_id[:8]))
                        break

        # Create configuration sensors for each charging station
        configurations_data = coordinator.data.get("configurations", {})
        _LOGGER.debug("Setting up configuration sensors for %s stations", len(configurations_data))
        _LOGGER.debug("Configuration data keys: %s", list(configurations_data.keys()))
        
        for station_id, station_data in configurations_data.items():
            _LOGGER.debug("Processing configuration for station %s: %s", station_id, station_data)
            station_info = station_data.get("station_info", {})
            configuration = station_data.get("configuration", [])
            
            _LOGGER.debug("Station %s configuration type: %s, length: %s", 
                         station_id, type(configuration), len(configuration) if isinstance(configuration, (list, dict)) else "N/A")
            
            if isinstance(configuration, list):
                config_count = 0
                for i, config_item in enumerate(configuration):
                    _LOGGER.debug("Configuration item %s for station %s: %s", i, station_id, config_item)
                    key = config_item.get("key")
                    value = config_item.get("value")
                    
                    # Only create sensors for configs with non-empty values
                    if key and value is not None and str(value).strip():
                        _LOGGER.debug("Creating configuration sensor for %s: %s=%s", station_id, key, value)
                        entities.append(
                            GaroEntityConfigurationSensor(
                                coordinator,
                                config_entry,
                                station_id,
                                station_info,
                                config_item
                            )
                        )
                        config_count += 1
                    else:
                        _LOGGER.debug("Skipping configuration %s for station %s (empty value): key=%s, value=%s", 
                                    i, station_id, key, value)
                
                _LOGGER.debug("Created %s configuration sensors for station %s", 
                            config_count, station_info.get("name", station_id[:8]))
            else:
                _LOGGER.warning("Configuration for station %s is not a list: %s", station_id, type(configuration))

        # Create transaction sensors for each charging station
        transactions_data = coordinator.data.get("transactions", {})
        _LOGGER.debug("Setting up transaction sensors for %s stations", len(transactions_data))
        
        for station_id, station_data in transactions_data.items():
            station_info = station_data.get("station_info", {})
            transactions = station_data.get("transactions", {})
            
            if isinstance(transactions, dict) and "items" in transactions and transactions["items"]:
                # Get the most recent transaction (first in list)
                most_recent_transaction = transactions["items"][0]
                
                # Create transaction status sensor
                entities.append(
                    GaroEntityTransactionStatusSensor(
                        coordinator,
                        config_entry,
                        station_id,
                        station_info,
                        most_recent_transaction
                    )
                )
                
                # Create transaction energy sensor
                entities.append(
                    GaroEntityTransactionEnergySensor(
                        coordinator,
                        config_entry,
                        station_id,
                        station_info,
                        most_recent_transaction
                    )
                )
                
                # Create transaction start time sensor
                entities.append(
                    GaroEntityTransactionStartTimeSensor(
                        coordinator,
                        config_entry,
                        station_id,
                        station_info,
                        most_recent_transaction
                    )
                )
                
                # Create transaction end time sensor
                entities.append(
                    GaroEntityTransactionEndTimeSensor(
                        coordinator,
                        config_entry,
                        station_id,
                        station_info,
                        most_recent_transaction
                    )
                )
                
                # Create transaction user sensor (only if transaction has an ID token)
                if most_recent_transaction.get("id_token"):
                    entities.append(
                        GaroEntityTransactionUserSensor(
                            coordinator,
                            config_entry,
                            station_id,
                            station_info,
                            most_recent_transaction
                        )
                    )
                
                _LOGGER.debug("Created transaction sensors for station %s", 
                            station_info.get("name", station_id[:8]))

        # Create charging unit and status sensors for each charging station
        charging_stations_data = coordinator.data.get("charging_stations", {})
        _LOGGER.debug("Setting up charging unit and status sensors for stations")
        
        if isinstance(charging_stations_data, dict) and "items" in charging_stations_data:
            for station in charging_stations_data["items"]:
                station_id = station.get("id")
                station_info = {
                    "name": station.get("name"),
                    "uid": station.get("uid"),
                    "id": station_id
                }
                
                # Create charging unit sensors
                charging_unit = station.get("charging_unit", {})
                if charging_unit:
                    unit_attributes = ["serial_number", "vendor_name", "model", "firmware_version"]
                    for attr in unit_attributes:
                        if charging_unit.get(attr):
                            entities.append(
                                GaroEntityChargingUnitSensor(
                                    coordinator,
                                    config_entry,
                                    station_id,
                                    station_info,
                                    attr,
                                    charging_unit.get(attr)
                                )
                            )
                    
                    _LOGGER.debug("Created charging unit sensors for station %s", 
                                station_info.get("name", station_id[:8]))
                
                # Create status sensors
                status = station.get("status", {})
                if status:
                    status_attributes = [
                        "connection", "registration", "installation", "configuration", 
                        "firmware_update", "heartbeat_timestamp", "last_firmware_update_check",
                        "configuration_sync_required", "using_proxy"
                    ]
                    for attr in status_attributes:
                        if status.get(attr) is not None:  # Include False values for booleans
                            entities.append(
                                GaroEntityStatusSensor(
                                    coordinator,
                                    config_entry,
                                    station_id,
                                    station_info,
                                    attr,
                                    status.get(attr)
                                )
                            )
                    
                    _LOGGER.debug("Created status sensors for station %s", 
                                station_info.get("name", station_id[:8]))
        
        _LOGGER.info("Created %s sensors for Garo Entity integration", len(entities))
        
    except Exception as exc:
        _LOGGER.error("Error during sensor setup, continuing with count sensor only: %s", exc)
        # Continue with just the count sensor if meter value setup fails

    async_add_entities(entities)


class GaroEntityDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Garo Entity data."""

    def __init__(self, hass: HomeAssistant, api: GaroEntityAPI) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=15),  # Less frequent updates for cloud API
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API."""
        import asyncio
        
        try:
            _LOGGER.debug("Fetching data from Garo Entity Cloud API")
            
            # Get charging stations count (fast operation)
            charging_stations_count = await asyncio.wait_for(
                self.api.get_charging_stations_count(), 
                timeout=30.0
            )
            _LOGGER.debug("Charging stations count: %s", charging_stations_count)
            
            # Get all meter values for non-load interface stations (potentially slow)
            try:
                all_meter_values = await asyncio.wait_for(
                    self.api.get_all_meter_values(),
                    timeout=60.0  # Longer timeout for meter values
                )
                _LOGGER.debug("Retrieved meter values for %s stations", len(all_meter_values))
            except asyncio.TimeoutError:
                _LOGGER.warning("Meter values fetch timed out, continuing with empty meter values")
                all_meter_values = {}
            except Exception as exc:
                _LOGGER.warning("Failed to fetch meter values, continuing without them: %s", exc)
                all_meter_values = {}

            # Get all connector statuses for non-load interface stations
            try:
                all_connector_statuses = await asyncio.wait_for(
                    self.api.get_all_connector_statuses(),
                    timeout=30.0  # Connector status should be fast
                )
                _LOGGER.debug("Retrieved connector statuses for %s stations", len(all_connector_statuses))
            except asyncio.TimeoutError:
                _LOGGER.warning("Connector status fetch timed out, continuing with empty statuses")
                all_connector_statuses = {}
            except Exception as exc:
                _LOGGER.warning("Failed to fetch connector statuses, continuing without them: %s", exc)
                all_connector_statuses = {}

            # Get all configuration values for non-load interface stations
            try:
                all_configurations = await asyncio.wait_for(
                    self.api.get_all_charging_station_configurations(),
                    timeout=30.0  # Configuration should be fast
                )
                _LOGGER.debug("Retrieved configurations for %s stations", len(all_configurations))
            except asyncio.TimeoutError:
                _LOGGER.warning("Configuration fetch timed out, continuing with empty configurations")
                all_configurations = {}
            except Exception as exc:
                _LOGGER.warning("Failed to fetch configurations, continuing without them: %s", exc)
                all_configurations = {}

            # Get all transactions for non-load interface stations
            try:
                all_transactions = await asyncio.wait_for(
                    self.api.get_all_transactions(),
                    timeout=30.0  # Transactions should be fast
                )
                _LOGGER.debug("Retrieved transactions for %s stations", len(all_transactions))
            except asyncio.TimeoutError:
                _LOGGER.warning("Transactions fetch timed out, continuing with empty transactions")
                all_transactions = {}
            except Exception as exc:
                _LOGGER.warning("Failed to fetch transactions, continuing without them: %s", exc)
                all_transactions = {}

            # Collect unique ID tokens from all transactions
            id_tokens = set()
            for station_data in all_transactions.values():
                transactions = station_data.get("transactions", {})
                if isinstance(transactions, dict) and "items" in transactions:
                    for transaction in transactions["items"]:
                        id_token = transaction.get("id_token")
                        if id_token:
                            id_tokens.add(id_token)

            _LOGGER.debug("Found %s unique ID tokens", len(id_tokens))

            # Get user information for all found ID tokens
            user_info = {}
            if id_tokens:
                try:
                    user_info = await asyncio.wait_for(
                        self.api.get_user_info_by_id_tokens(list(id_tokens)),
                        timeout=15.0
                    )
                    _LOGGER.debug("Retrieved user info for %s tokens", len(user_info))
                except asyncio.TimeoutError:
                    _LOGGER.warning("User info fetch timed out, continuing without user info")
                except Exception as exc:
                    _LOGGER.warning("Failed to fetch user info, continuing without it: %s", exc)
            
            # Get charging stations with relationships
            try:
                charging_stations = await asyncio.wait_for(
                    self.api.get_charging_stations(),
                    timeout=30.0
                )
                _LOGGER.debug("Retrieved charging stations with relationships")
            except asyncio.TimeoutError:
                _LOGGER.warning("Charging stations fetch timed out, continuing with empty data")
                charging_stations = {}
            except Exception as exc:
                _LOGGER.warning("Failed to fetch charging stations, continuing without them: %s", exc)
                charging_stations = {}
            
            return {
                "charging_stations_count": charging_stations_count,
                "charging_stations": charging_stations,
                "meter_values": all_meter_values,
                "connector_statuses": all_connector_statuses,
                "configurations": all_configurations,
                "transactions": all_transactions,
                "user_info": user_info,
            }
        except Exception as exc:
            _LOGGER.error("Error communicating with API: %s", exc)
            raise UpdateFailed(f"Error communicating with API: {exc}") from exc


class GaroEntityChargingStationsCountSensor(CoordinatorEntity, SensorEntity):
    """Sensor for number of charging stations."""

    _attr_icon = "mdi:ev-station"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self, coordinator: GaroEntityDataUpdateCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{config_entry.entry_id}_charging_stations_count"
        self._attr_name = "Charging Stations Count"

    @property
    def native_value(self) -> int | None:
        """Return the number of charging stations."""
        if not self.coordinator.data:
            _LOGGER.debug("No coordinator data available")
            return None
            
        count = self.coordinator.data.get("charging_stations_count")
        _LOGGER.debug("Returning charging stations count: %s", count)
        
        return count

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        return {
            "last_update": self.coordinator.last_update_success,
            "api_type": "Cloud API",
        }


class GaroEntityMeterValueSensor(CoordinatorEntity, SensorEntity):
    """Sensor for meter values from charging stations."""

    def __init__(
        self,
        coordinator: GaroEntityDataUpdateCoordinator,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        unique_key: str,
        meter_data: dict[str, Any],
    ) -> None:
        """Initialize the meter value sensor."""
        super().__init__(coordinator)
        
        self.station_id = station_id
        self.station_info = station_info
        self.unique_key = unique_key
        self.initial_meter_data = meter_data
        
        # Extract components from unique key
        self.measure_name = meter_data.get("measure_name")
        self.phase = meter_data.get("phase")
        self.location = meter_data.get("location")
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        
        # Create unique ID and name including phase information
        unique_clean = unique_key.replace(".", "_").lower()
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_{unique_clean}"
        self._attr_name = self._format_sensor_name(station_name, self.measure_name, self.phase, self.location)
        
        # Set device class and unit based on measure type
        self._set_device_attributes(self.measure_name, meter_data.get("unit"))

    def _format_sensor_name(self, station_name: str, measure_name: str, phase: str, location: str) -> str:
        """Format sensor name including phase and location information."""
        # Convert measure names to friendly names
        name_map = {
            "Energy.Active.Import.Register": "Energy Import",
            "Power.Active.Import": "Active Power",
            "Current.Import": "Current Import",
            "Current.Export": "Current Export", 
            "Current.Offered": "Current Offered",
            "Voltage": "Voltage",
            "Frequency": "Frequency",
            "Temperature": "Temperature",
        }
        
        base_name = name_map.get(measure_name, measure_name.replace(".", " ").title())
        
        # Build name with phase and location
        name_parts = [station_name, base_name]
        
        if phase:
            name_parts.append(phase)
        
        if location:
            name_parts.append(location)
            
        return " ".join(name_parts)

    def _format_measure_name(self, measure_name: str) -> str:
        """Format measure name for display (legacy method)."""
        # Convert measure names to friendly names
        name_map = {
            "Energy.Active.Import.Register": "Energy Import",
            "Power.Active.Import": "Active Power",
            "Current.Import": "Current",
            "Voltage": "Voltage",
            "Frequency": "Frequency",
            "Temperature": "Temperature",
        }
        return name_map.get(measure_name, measure_name.replace(".", " ").title())

    def _normalize_unit(self, unit: str) -> str:
        """Normalize unit to Home Assistant expected format."""
        if not unit:
            return unit
            
        # Unit mappings for Home Assistant compatibility
        unit_mappings = {
            "celsius": "°C",
            "fahrenheit": "°F",
            "kelvin": "K",
            "watt": "W",
            "kilowatt": "kW",
            "volt": "V",
            "ampere": "A",
            "amp": "A",
            "hertz": "Hz",
            "watthour": "Wh",
            "kilowatthour": "kWh",
        }
        
        unit_lower = unit.lower()
        return unit_mappings.get(unit_lower, unit)

    def _set_device_attributes(self, measure_name: str, unit: str) -> None:
        """Set device class, state class and icon based on measure type."""        
        if "energy" in measure_name.lower():
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            self._attr_icon = "mdi:lightning-bolt"
        elif "power" in measure_name.lower():
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:flash"
        elif "current" in measure_name.lower():
            self._attr_device_class = SensorDeviceClass.CURRENT
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:current-ac"
        elif "voltage" in measure_name.lower():
            self._attr_device_class = SensorDeviceClass.VOLTAGE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:sine-wave"
        elif "frequency" in measure_name.lower():
            self._attr_device_class = SensorDeviceClass.FREQUENCY
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:waveform"
        elif "temperature" in measure_name.lower():
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:thermometer"
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:gauge"
        
        # Set native unit with normalization
        self._attr_native_unit_of_measurement = self._normalize_unit(unit)

    @property
    def native_value(self) -> float | None:
        """Return the current meter value."""
        if not self.coordinator.data:
            return None
            
        meter_values_data = self.coordinator.data.get("meter_values", {})
        station_data = meter_values_data.get(self.station_id)
        
        if not station_data:
            return None
            
        meter_values = station_data.get("meter_values", [])
        if not isinstance(meter_values, list):
            return None
        
        # Find the most recent value for this specific measure type, phase, and location
        latest_value = None
        latest_time = ""
        
        for item in meter_values:
            # Match measure name, phase, and location exactly
            if (item.get("measure_name") == self.measure_name and
                item.get("phase") == self.phase and
                item.get("location") == self.location):
                
                item_time = item.get("time", "")
                if item_time > latest_time:
                    latest_time = item_time
                    latest_value = item.get("measure_value")
        
        if latest_value is not None:
            try:
                return float(latest_value)
            except (ValueError, TypeError):
                _LOGGER.warning("Could not convert meter value to float: %s", latest_value)
                return None
        
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return None
            
        meter_values_data = self.coordinator.data.get("meter_values", {})
        station_data = meter_values_data.get(self.station_id)
        
        if not station_data:
            return None
            
        # Get the latest meter reading for additional attributes
        meter_values = station_data.get("meter_values", [])
        if isinstance(meter_values, list):
            latest_item = None
            latest_time = ""
            
            for item in meter_values:
                # Match measure name, phase, and location exactly
                if (item.get("measure_name") == self.measure_name and
                    item.get("phase") == self.phase and
                    item.get("location") == self.location):
                    
                    item_time = item.get("time", "")
                    if item_time > latest_time:
                        latest_time = item_time
                        latest_item = item
            
            if latest_item:
                return {
                    "station_name": self.station_info.get("name"),
                    "station_uid": self.station_info.get("uid"),
                    "charging_station_id": self.station_id,
                    "connector_id": latest_item.get("connector_id"),
                    "transaction_id": latest_item.get("transaction_id"),
                    "last_reading_time": latest_item.get("time"),
                    "context": latest_item.get("context"),
                    "phase": latest_item.get("phase"),
                    "location": latest_item.get("location"),
                }
        
        return {
            "station_name": self.station_info.get("name"),
            "station_uid": self.station_info.get("uid"),
            "charging_station_id": self.station_id,
        }


class GaroEntityConnectorStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for connector status from charging stations."""

    _attr_icon = "mdi:ev-plug-type2"

    def __init__(
        self,
        coordinator: GaroEntityDataUpdateCoordinator,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        connector_data: dict[str, Any],
    ) -> None:
        """Initialize the connector status sensor."""
        super().__init__(coordinator)
        
        self.station_id = station_id
        self.station_info = station_info
        self.connector_id = connector_data.get("connector_id", 1)
        self.initial_connector_data = connector_data
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        
        # Create unique ID and name
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_connector_{self.connector_id}"
        self._attr_name = f"{station_name} Connector {self.connector_id} Status"

    @property
    def native_value(self) -> str | None:
        """Return the current connector status."""
        if not self.coordinator.data:
            return None
            
        connector_statuses_data = self.coordinator.data.get("connector_statuses", {})
        station_data = connector_statuses_data.get(self.station_id)
        
        if not station_data:
            return None
            
        connector_status = station_data.get("connector_status", [])
        if not isinstance(connector_status, list):
            return None
        
        # Find the connector with matching ID
        for connector in connector_status:
            if connector.get("connector_id") == self.connector_id:
                status = connector.get("status")
                if status:
                    return self._format_status(status)
        
        return None

    def _format_status(self, status: str) -> str:
        """Format status for display."""
        # Map status to friendly names
        status_map = {
            "Available": "Available",
            "SuspendedEV": "Suspended by EV", 
            "SuspendedEVSE": "Suspended by EVSE",
            "Occupied": "Occupied",
            "Preparing": "Preparing",
            "Charging": "Charging",
            "Finishing": "Finishing",
            "Faulted": "Faulted",
            "Unavailable": "Unavailable",
            "Reserved": "Reserved",
        }
        return status_map.get(status, status)

    @property
    def icon(self) -> str:
        """Return icon based on status."""
        status = self.native_value
        if status in ["Charging"]:
            return "mdi:ev-plug-ccs2"
        elif status in ["Available"]:
            return "mdi:ev-plug-type2"
        elif status in ["Occupied", "Preparing"]:
            return "mdi:ev-plug-chademo"
        elif status in ["Faulted", "Unavailable"]:
            return "mdi:alert-circle"
        elif status in ["Suspended by EV", "Suspended by EVSE"]:
            return "mdi:pause-circle"
        else:
            return "mdi:ev-plug-type2"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return None
            
        connector_statuses_data = self.coordinator.data.get("connector_statuses", {})
        station_data = connector_statuses_data.get(self.station_id)
        
        if not station_data:
            return None
            
        # Get the connector data for additional attributes
        connector_status = station_data.get("connector_status", [])
        if isinstance(connector_status, list):
            for connector in connector_status:
                if connector.get("connector_id") == self.connector_id:
                    return {
                        "station_name": self.station_info.get("name"),
                        "station_uid": self.station_info.get("uid"),
                        "charging_station_id": self.station_id,
                        "connector_id": self.connector_id,
                        "status_id": connector.get("id"),
                        "timestamp": connector.get("timestamp"),
                        "limited": connector.get("limited", False),
                        "raw_status": connector.get("status"),
                    }
        
        return {
            "station_name": self.station_info.get("name"),
            "station_uid": self.station_info.get("uid"),
            "charging_station_id": self.station_id,
            "connector_id": self.connector_id,
        }


class GaroEntityConfigurationSensor(CoordinatorEntity, SensorEntity):
    """Sensor for configuration values from charging stations."""

    def __init__(
        self,
        coordinator: GaroEntityDataUpdateCoordinator,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        config_item: dict[str, Any],
    ) -> None:
        """Initialize the configuration sensor."""
        super().__init__(coordinator)
        
        self.station_id = station_id
        self.station_info = station_info
        self.config_key = config_item.get("key")
        self.initial_config_item = config_item
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        
        # Create unique ID and name
        config_clean = self.config_key.replace(".", "_").replace("Garo", "").lower()
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_config_{config_clean}"
        self._attr_name = f"{station_name} {self._format_config_name(self.config_key)}"
        
        # Set icon and attributes based on config type
        self._set_config_attributes(self.config_key, config_item.get("value"))

    def _format_config_name(self, key: str) -> str:
        """Format configuration key name for display."""
        # Remove Garo prefix and format nicely
        name = key.replace("Garo", "").replace("_", " ")
        
        # Special mappings for common config keys
        name_map = {
            "LightIntensity": "Light Intensity",
            "ConnectionGroupMaster": "Connection Group Master",
            "ConnectionGroupMaxCurrent": "Max Current (Group)",
            "ConnectionGroupName": "Connection Group Name",
            "ConnectionGroupDevices1": "Connection Group Device 1",
            "ConnectionGroupDevices2": "Connection Group Device 2",
            "ConnectionGroupDevices3": "Connection Group Device 3",
            "ConnectionGroupDevices4": "Connection Group Device 4",
            "BracketMaxCurrent": "Max Current (Bracket)",
            "OwnerMaxCurrent": "Max Current (Owner)",
            "NetworkInterface": "Network Interface",
            "ModemApn": "Modem APN",
            "ModemPin": "Modem PIN",
            "TimeZone": "Time Zone",
            "FreeChargeTag": "Free Charge Tag",
            "ClockAlignedDataIntervalSpread": "Data Interval Spread",
        }
        
        return name_map.get(key.replace("Garo", ""), name.title())

    def _set_config_attributes(self, key: str, value: any) -> None:
        """Set device attributes based on configuration type."""
        key_lower = key.lower()
        
        if "current" in key_lower:
            self._attr_icon = "mdi:current-ac"
            self._attr_native_unit_of_measurement = "A"
        elif "light" in key_lower or "intensity" in key_lower:
            self._attr_icon = "mdi:brightness-6"
            self._attr_native_unit_of_measurement = "%"
        elif "network" in key_lower or "interface" in key_lower:
            self._attr_icon = "mdi:network"
        elif "modem" in key_lower:
            self._attr_icon = "mdi:cellphone"
        elif "time" in key_lower or "zone" in key_lower:
            self._attr_icon = "mdi:clock"
        elif "group" in key_lower and "name" in key_lower:
            self._attr_icon = "mdi:group"
        elif "master" in key_lower:
            self._attr_icon = "mdi:crown"
        elif "tag" in key_lower:
            self._attr_icon = "mdi:tag"
        elif "interval" in key_lower or "spread" in key_lower:
            self._attr_icon = "mdi:timer"
            self._attr_native_unit_of_measurement = "s"
        else:
            self._attr_icon = "mdi:cog"

    @property
    def native_value(self) -> str | int | float | bool | None:
        """Return the current configuration value."""
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
                
                # Try to convert to appropriate type
                if isinstance(value, (bool, int, float)):
                    return value
                elif isinstance(value, str):
                    # Try to convert string representations
                    if value.lower() in ["true", "false"]:
                        return value.lower() == "true"
                    try:
                        # Try int first
                        return int(value)
                    except ValueError:
                        try:
                            # Try float
                            return float(value)
                        except ValueError:
                            # Return as string
                            return value
                return value
        
        return None

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
                        "mutability": config_item.get("mutability"),
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


class GaroEntityTransactionStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the current transaction status."""

    _attr_icon = "mdi:battery-charging"

    def __init__(
        self,
        coordinator: GaroEntityDataUpdateCoordinator,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        initial_transaction: dict[str, Any],
    ) -> None:
        """Initialize the transaction status sensor."""
        super().__init__(coordinator)
        
        self.station_id = station_id
        self.station_info = station_info
        self.connector_id = initial_transaction.get("connector_id", 1)
        self.initial_transaction = initial_transaction
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        
        # Create unique ID and name
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_transaction_status"
        self._attr_name = f"{station_name} Transaction Status"

    @property
    def native_value(self) -> str | None:
        """Return the current transaction status."""
        transaction = self._get_most_recent_transaction()
        if transaction:
            status = transaction.get("state", "Unknown")
            return self._format_transaction_status(status)
        return None

    def _format_transaction_status(self, status: str) -> str:
        """Format transaction status for display."""
        status_map = {
            "Started": "Started",
            "Finished": "Finished",
            "Stopped": "Stopped",
            "Authorized": "Authorized",
            "Preparing": "Preparing",
        }
        return status_map.get(status, status)

    @property
    def icon(self) -> str:
        """Return icon based on transaction status."""
        status = self.native_value
        if status == "Started":
            return "mdi:battery-charging"
        elif status == "Finished":
            return "mdi:battery-check"
        elif status == "Stopped":
            return "mdi:battery-remove"
        else:
            return "mdi:battery"

    def _get_most_recent_transaction(self) -> dict[str, Any] | None:
        """Get the most recent transaction."""
        if not self.coordinator.data:
            return None
            
        transactions_data = self.coordinator.data.get("transactions", {})
        station_data = transactions_data.get(self.station_id)
        
        if not station_data:
            return None
            
        transactions = station_data.get("transactions", {})
        if isinstance(transactions, dict) and "items" in transactions and transactions["items"]:
            return transactions["items"][0]  # First item is most recent
            
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        transaction = self._get_most_recent_transaction()
        if not transaction:
            return None
            
        return {
            "station_name": self.station_info.get("name"),
            "station_uid": self.station_info.get("uid"),
            "charging_station_id": self.station_id,
            "transaction_id": transaction.get("id"),
            "connector_id": transaction.get("connector_id"),
            "id_token": transaction.get("id_token"),
            "start_time": transaction.get("start_time"),
            "end_time": transaction.get("end_time"),
            "meter_start": transaction.get("meter_start"),
            "meter_stop": transaction.get("meter_stop"),
        }


class GaroEntityTransactionEnergySensor(CoordinatorEntity, SensorEntity):
    """Sensor for energy charged in the current/last transaction."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "Wh"
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self,
        coordinator: GaroEntityDataUpdateCoordinator,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        initial_transaction: dict[str, Any],
    ) -> None:
        """Initialize the transaction energy sensor."""
        super().__init__(coordinator)
        
        self.station_id = station_id
        self.station_info = station_info
        self.connector_id = initial_transaction.get("connector_id", 1)
        self.initial_transaction = initial_transaction
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        
        # Create unique ID and name
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_transaction_energy"
        self._attr_name = f"{station_name} Transaction Energy"

    @property
    def native_value(self) -> float | None:
        """Return the energy charged in the transaction."""
        transaction = self._get_most_recent_transaction()
        if not transaction:
            return None
            
        meter_start = transaction.get("meter_start")
        meter_stop = transaction.get("meter_stop")
        
        if meter_start is not None:
            if meter_stop is not None:
                # Completed transaction - calculate energy charged
                energy_charged = meter_stop - meter_start
                _LOGGER.debug("Transaction energy: %s - %s = %s Wh", meter_stop, meter_start, energy_charged)
                return float(energy_charged)
            else:
                # Ongoing transaction - use current meter reading from energy meter if available
                current_energy = self._get_current_energy_reading()
                if current_energy is not None and current_energy >= meter_start:
                    energy_charged = current_energy - meter_start
                    _LOGGER.debug("Ongoing transaction energy: %s - %s = %s Wh", current_energy, meter_start, energy_charged)
                    return float(energy_charged)
                else:
                    # No current reading available, return 0 for started transaction
                    return 0.0
        
        return None

    def _get_current_energy_reading(self) -> float | None:
        """Get current energy reading from meter values."""
        if not self.coordinator.data:
            return None
            
        meter_values_data = self.coordinator.data.get("meter_values", {})
        station_data = meter_values_data.get(self.station_id)
        
        if not station_data:
            return None
            
        meter_values = station_data.get("meter_values", [])
        if isinstance(meter_values, list):
            # Find Energy.Active.Import.Register value
            for item in meter_values:
                if item.get("measure_name") == "Energy.Active.Import.Register":
                    try:
                        return float(item.get("measure_value", 0))
                    except (ValueError, TypeError):
                        continue
        
        return None

    def _get_most_recent_transaction(self) -> dict[str, Any] | None:
        """Get the most recent transaction."""
        if not self.coordinator.data:
            return None
            
        transactions_data = self.coordinator.data.get("transactions", {})
        station_data = transactions_data.get(self.station_id)
        
        if not station_data:
            return None
            
        transactions = station_data.get("transactions", {})
        if isinstance(transactions, dict) and "items" in transactions and transactions["items"]:
            return transactions["items"][0]  # First item is most recent
            
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        transaction = self._get_most_recent_transaction()
        if not transaction:
            return None
            
        meter_start = transaction.get("meter_start")
        meter_stop = transaction.get("meter_stop")
        current_energy = self._get_current_energy_reading()
        
        return {
            "station_name": self.station_info.get("name"),
            "station_uid": self.station_info.get("uid"),
            "charging_station_id": self.station_id,
            "transaction_id": transaction.get("id"),
            "transaction_state": transaction.get("state"),
            "meter_start": meter_start,
            "meter_stop": meter_stop,
            "current_meter_reading": current_energy,
            "start_time": transaction.get("start_time"),
            "end_time": transaction.get("end_time"),
        }


class GaroEntityTransactionStartTimeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for transaction start time."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(
        self,
        coordinator: GaroEntityDataUpdateCoordinator,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        initial_transaction: dict[str, Any],
    ) -> None:
        """Initialize the transaction start time sensor."""
        super().__init__(coordinator)
        
        self.station_id = station_id
        self.station_info = station_info
        self.connector_id = initial_transaction.get("connector_id", 1)
        self.initial_transaction = initial_transaction
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        
        # Create unique ID and name
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_transaction_start_time"
        self._attr_name = f"{station_name} Transaction Start Time"

    @property
    def native_value(self) -> datetime | None:
        """Return the transaction start time."""
        transaction = self._get_most_recent_transaction()
        if transaction:
            start_time = transaction.get("start_time")
            if start_time:
                try:
                    # Parse ISO format timestamp string to datetime object
                    return datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                except (ValueError, AttributeError) as exc:
                    _LOGGER.warning("Failed to parse start_time '%s' for station %s: %s", start_time, self.station_id, exc)
                    return None
        return None

    def _get_most_recent_transaction(self) -> dict[str, Any] | None:
        """Get the most recent transaction."""
        if not self.coordinator.data:
            return None
            
        transactions_data = self.coordinator.data.get("transactions", {})
        station_data = transactions_data.get(self.station_id)
        
        if not station_data:
            return None
            
        transactions = station_data.get("transactions", {})
        if isinstance(transactions, dict) and "items" in transactions and transactions["items"]:
            return transactions["items"][0]  # First item is most recent
            
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        transaction = self._get_most_recent_transaction()
        if not transaction:
            return None
            
        return {
            "station_name": self.station_info.get("name"),
            "station_uid": self.station_info.get("uid"),
            "charging_station_id": self.station_id,
            "transaction_id": transaction.get("id"),
            "transaction_state": transaction.get("state"),
            "connector_id": transaction.get("connector_id"),
            "end_time": transaction.get("end_time"),
        }


class GaroEntityTransactionEndTimeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for transaction end time."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-end"

    def __init__(
        self,
        coordinator: GaroEntityDataUpdateCoordinator,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        initial_transaction: dict[str, Any],
    ) -> None:
        """Initialize the transaction end time sensor."""
        super().__init__(coordinator)
        
        self.station_id = station_id
        self.station_info = station_info
        self.connector_id = initial_transaction.get("connector_id", 1)
        self.initial_transaction = initial_transaction
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        
        # Create unique ID and name
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_transaction_end_time"
        self._attr_name = f"{station_name} Transaction End Time"

    @property
    def native_value(self) -> datetime | None:
        """Return the transaction end time."""
        transaction = self._get_most_recent_transaction()
        if transaction:
            end_time = transaction.get("end_time")
            if end_time:
                try:
                    # Parse ISO format timestamp string to datetime object
                    return datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                except (ValueError, AttributeError) as exc:
                    _LOGGER.warning("Failed to parse end_time '%s' for station %s: %s", end_time, self.station_id, exc)
                    return None
        return None

    def _get_most_recent_transaction(self) -> dict[str, Any] | None:
        """Get the most recent transaction."""
        if not self.coordinator.data:
            return None
            
        transactions_data = self.coordinator.data.get("transactions", {})
        station_data = transactions_data.get(self.station_id)
        
        if not station_data:
            return None
            
        transactions = station_data.get("transactions", {})
        if isinstance(transactions, dict) and "items" in transactions and transactions["items"]:
            return transactions["items"][0]  # First item is most recent
            
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        transaction = self._get_most_recent_transaction()
        if not transaction:
            return None
            
        return {
            "station_name": self.station_info.get("name"),
            "station_uid": self.station_info.get("uid"),
            "charging_station_id": self.station_id,
            "transaction_id": transaction.get("id"),
            "transaction_state": transaction.get("state"),
            "connector_id": transaction.get("connector_id"),
            "start_time": transaction.get("start_time"),
        }


class GaroEntityChargingUnitSensor(CoordinatorEntity, SensorEntity):
    """Sensor for charging unit information."""

    def __init__(
        self,
        coordinator: GaroEntityDataUpdateCoordinator,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        attribute_name: str,
        attribute_value: Any,
    ) -> None:
        """Initialize the charging unit sensor."""
        super().__init__(coordinator)
        
        self.station_id = station_id
        self.station_info = station_info
        self.attribute_name = attribute_name
        self.initial_value = attribute_value
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        
        # Create unique ID and name
        attr_clean = attribute_name.replace("_", " ").title()
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_unit_{attribute_name}"
        self._attr_name = f"{station_name} {attr_clean}"
        
        # Set icon and attributes based on attribute type
        self._set_unit_attributes(attribute_name)

    def _set_unit_attributes(self, attribute_name: str) -> None:
        """Set device attributes based on attribute type."""
        if attribute_name == "serial_number":
            self._attr_icon = "mdi:identifier"
        elif attribute_name == "model":
            self._attr_icon = "mdi:ev-station"
        elif attribute_name == "vendor_name":
            self._attr_icon = "mdi:factory"
        elif attribute_name == "firmware_version":
            self._attr_icon = "mdi:chip"
        else:
            self._attr_icon = "mdi:information"

    @property
    def native_value(self) -> str | None:
        """Return the charging unit attribute value."""
        if not self.coordinator.data:
            return None
            
        # Get station data with relationships
        charging_stations_data = self.coordinator.data.get("charging_stations", {})
        if isinstance(charging_stations_data, dict) and "items" in charging_stations_data:
            for station in charging_stations_data["items"]:
                if station.get("id") == self.station_id:
                    charging_unit = station.get("charging_unit", {})
                    return charging_unit.get(self.attribute_name)
        
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return None
            
        charging_stations_data = self.coordinator.data.get("charging_stations", {})
        if isinstance(charging_stations_data, dict) and "items" in charging_stations_data:
            for station in charging_stations_data["items"]:
                if station.get("id") == self.station_id:
                    charging_unit = station.get("charging_unit", {})
                    return {
                        "station_name": self.station_info.get("name"),
                        "station_uid": self.station_info.get("uid"),
                        "charging_station_id": self.station_id,
                        "unit_id": charging_unit.get("id"),
                        "serial_number": charging_unit.get("serial_number"),
                        "vendor_name": charging_unit.get("vendor_name"),
                        "model": charging_unit.get("model"),
                        "firmware_version": charging_unit.get("firmware_version"),
                        "modem_id": charging_unit.get("modem_id"),
                    }
        
        return {
            "station_name": self.station_info.get("name"),
            "station_uid": self.station_info.get("uid"),
            "charging_station_id": self.station_id,
        }


class GaroEntityStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for charging station status information."""

    def __init__(
        self,
        coordinator: GaroEntityDataUpdateCoordinator,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        attribute_name: str,
        attribute_value: Any,
    ) -> None:
        """Initialize the status sensor."""
        super().__init__(coordinator)
        
        self.station_id = station_id
        self.station_info = station_info
        self.attribute_name = attribute_name
        self.initial_value = attribute_value
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        
        # Create unique ID and name
        attr_clean = attribute_name.replace("_", " ").title()
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_status_{attribute_name}"
        self._attr_name = f"{station_name} {attr_clean}"
        
        # Set icon and device class based on attribute type
        self._set_status_attributes(attribute_name)

    def _set_status_attributes(self, attribute_name: str) -> None:
        """Set device attributes based on attribute type."""
        if attribute_name == "connection":
            self._attr_icon = "mdi:wifi"
        elif attribute_name == "registration":
            self._attr_icon = "mdi:check-circle"
        elif attribute_name == "installation":
            self._attr_icon = "mdi:tools"
        elif attribute_name == "configuration":
            self._attr_icon = "mdi:cog"
        elif attribute_name == "firmware_update":
            self._attr_icon = "mdi:update"
        elif attribute_name == "heartbeat_timestamp":
            self._attr_icon = "mdi:heart-pulse"
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif attribute_name == "last_firmware_update_check":
            self._attr_icon = "mdi:clock-check"
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif attribute_name == "configuration_sync_required":
            self._attr_icon = "mdi:sync"
        elif attribute_name == "using_proxy":
            self._attr_icon = "mdi:shield-network"
        else:
            self._attr_icon = "mdi:information"

    @property
    def native_value(self) -> str | datetime | bool | None:
        """Return the status attribute value."""
        if not self.coordinator.data:
            return None
            
        # Get station data with relationships
        charging_stations_data = self.coordinator.data.get("charging_stations", {})
        if isinstance(charging_stations_data, dict) and "items" in charging_stations_data:
            for station in charging_stations_data["items"]:
                if station.get("id") == self.station_id:
                    status = station.get("status", {})
                    value = status.get(self.attribute_name)
                    
                    # Parse timestamp values for timestamp sensors
                    if self.attribute_name in ["heartbeat_timestamp", "last_firmware_update_check"] and value:
                        try:
                            return datetime.fromisoformat(value.replace('Z', '+00:00'))
                        except (ValueError, AttributeError):
                            return None
                    
                    return value
        
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return None
            
        charging_stations_data = self.coordinator.data.get("charging_stations", {})
        if isinstance(charging_stations_data, dict) and "items" in charging_stations_data:
            for station in charging_stations_data["items"]:
                if station.get("id") == self.station_id:
                    status = station.get("status", {})
                    return {
                        "station_name": self.station_info.get("name"),
                        "station_uid": self.station_info.get("uid"),
                        "charging_station_id": self.station_id,
                        "connection": status.get("connection"),
                        "registration": status.get("registration"),
                        "installation": status.get("installation"),
                        "configuration": status.get("configuration"),
                        "firmware_update": status.get("firmware_update"),
                        "configuration_sync_required": status.get("configuration_sync_required"),
                        "using_proxy": status.get("using_proxy"),
                        "latest_firmware_update_id": status.get("latest_firmware_update_id"),
                    }
        
        return {
            "station_name": self.station_info.get("name"),
            "station_uid": self.station_info.get("uid"),
            "charging_station_id": self.station_id,
        }


class GaroEntityTransactionUserSensor(CoordinatorEntity, SensorEntity):
    """Sensor for transaction user name."""

    _attr_icon = "mdi:account"

    def __init__(
        self,
        coordinator: GaroEntityDataUpdateCoordinator,
        config_entry: ConfigEntry,
        station_id: str,
        station_info: dict[str, Any],
        initial_transaction: dict[str, Any],
    ) -> None:
        """Initialize the transaction user sensor."""
        super().__init__(coordinator)
        
        self.station_id = station_id
        self.station_info = station_info
        self.connector_id = initial_transaction.get("connector_id", 1)
        self.initial_transaction = initial_transaction
        
        station_name = station_info.get("name", station_info.get("uid", station_id[:8]))
        
        # Create unique ID and name
        self._attr_unique_id = f"{config_entry.entry_id}_{station_id}_transaction_user"
        self._attr_name = f"{station_name} Transaction User"

    @property
    def native_value(self) -> str | None:
        """Return the transaction user's full name."""
        transaction = self._get_most_recent_transaction()
        if not transaction:
            return None
            
        id_token = transaction.get("id_token")
        if not id_token:
            return None
            
        # Get user info from coordinator data
        user_info_data = self.coordinator.data.get("user_info", {}) if self.coordinator.data else {}
        user_info = user_info_data.get(id_token)
        
        _LOGGER.debug("Transaction user sensor for station %s: found_user_info=%s", 
                     self.station_id, user_info is not None)
        
        if user_info:
            first_name = user_info.get("first_name", "")
            last_name = user_info.get("last_name", "")
            
            # Return full name or just first name if last name is missing
            if first_name and last_name:
                return f"{first_name} {last_name}"
            elif first_name:
                return first_name
            elif last_name:
                return last_name
            else:
                # Fallback to email if no names available
                email = user_info.get("email")
                if email:
                    return email.split("@")[0]  # Use part before @ as display name
        
        # Fallback to ID token if no user info found
        return id_token

    def _get_most_recent_transaction(self) -> dict[str, Any] | None:
        """Get the most recent transaction."""
        if not self.coordinator.data:
            return None
            
        transactions_data = self.coordinator.data.get("transactions", {})
        station_data = transactions_data.get(self.station_id)
        
        if not station_data:
            return None
            
        transactions = station_data.get("transactions", {})
        if isinstance(transactions, dict) and "items" in transactions and transactions["items"]:
            return transactions["items"][0]  # First item is most recent
            
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        transaction = self._get_most_recent_transaction()
        return self.coordinator.last_update_success and transaction is not None and transaction.get("id_token") is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        transaction = self._get_most_recent_transaction()
        if not transaction:
            return None
            
        id_token = transaction.get("id_token")
        if not id_token:
            return None
            
        # Get user info from coordinator data
        user_info_data = self.coordinator.data.get("user_info", {}) if self.coordinator.data else {}
        user_info = user_info_data.get(id_token, {})
        
        attributes = {
            "station_name": self.station_info.get("name"),
            "station_uid": self.station_info.get("uid"),
            "charging_station_id": self.station_id,
            "transaction_id": transaction.get("id"),
            "transaction_state": transaction.get("state"),
            "connector_id": transaction.get("connector_id"),
            "id_token": id_token,
        }
        
        # Add user info if available
        if user_info:
            attributes.update({
                "user_id": user_info.get("id"),
                "email": user_info.get("email"),
                "first_name": user_info.get("first_name"),
                "last_name": user_info.get("last_name"),
                "locale": user_info.get("locale"),
                "virtual_id_token": user_info.get("virtual_id_token"),
            })
        
        return attributes