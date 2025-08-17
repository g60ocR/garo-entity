"""API client for Garo Entity Cloud API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
import asyncio
import boto3
import json
from botocore.exceptions import ClientError

from .const import DEFAULT_COGNITO_CLIENT_ID, DEFAULT_COGNITO_REGION, DEFAULT_API_BASE_URL

_LOGGER = logging.getLogger(__name__)


class GaroEntityAPI:
    """API client for Garo Entity Cloud API."""

    def __init__(
        self, 
        username: str, 
        password: str,
        cognito_client_id: str = DEFAULT_COGNITO_CLIENT_ID,
        cognito_region: str = DEFAULT_COGNITO_REGION,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        """Initialize the API client."""
        self.username = username
        self.password = password
        self.cognito_client_id = cognito_client_id
        self.cognito_region = cognito_region
        self.api_base_url = api_base_url
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        self.cognito_client = None

    async def _get_cognito_client(self):
        """Get the Cognito client, creating it if necessary."""
        if self.cognito_client is None:
            self.cognito_client = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: boto3.client('cognito-idp', region_name=self.cognito_region)
            )
        return self.cognito_client

    async def _authenticate(self) -> bool:
        """Authenticate with AWS Cognito and get access token."""
        try:
            _LOGGER.debug("Authenticating with Garo Entity cloud API")
            
            cognito_client = await self._get_cognito_client()
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: cognito_client.initiate_auth(
                    ClientId=self.cognito_client_id,
                    AuthFlow='USER_PASSWORD_AUTH',
                    AuthParameters={
                        'USERNAME': self.username,
                        'PASSWORD': self.password
                    }
                )
            )
            
            auth_result = response['AuthenticationResult']
            self.access_token = auth_result['AccessToken']
            self.refresh_token = auth_result['RefreshToken']
            
            # Calculate token expiration (expires in seconds from response)
            expires_in = auth_result.get('ExpiresIn', 3600)
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
            
            _LOGGER.debug("Authentication successful, token expires at %s", self.token_expires_at)
            return True
            
        except ClientError as exc:
            _LOGGER.error("Authentication failed: %s", exc)
            _LOGGER.error("Error code: %s", exc.response.get('Error', {}).get('Code'))
            _LOGGER.error("Error message: %s", exc.response.get('Error', {}).get('Message'))
            return False
        except Exception as exc:
            _LOGGER.error("Unexpected authentication error: %s", exc)
            return False

    async def _refresh_access_token(self) -> bool:
        """Refresh the access token using refresh token."""
        if not self.refresh_token:
            return await self._authenticate()
            
        try:
            _LOGGER.debug("Refreshing access token")
            
            cognito_client = await self._get_cognito_client()
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: cognito_client.initiate_auth(
                    ClientId=self.cognito_client_id,
                    AuthFlow='REFRESH_TOKEN_AUTH',
                    AuthParameters={
                        'REFRESH_TOKEN': self.refresh_token
                    }
                )
            )
            
            auth_result = response['AuthenticationResult']
            self.access_token = auth_result['AccessToken']
            
            # Update expiration
            expires_in = auth_result.get('ExpiresIn', 3600)
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
            
            _LOGGER.debug("Token refreshed successfully")
            return True
            
        except ClientError as exc:
            _LOGGER.error("Token refresh failed: %s", exc)
            return await self._authenticate()

    async def _ensure_valid_token(self) -> bool:
        """Ensure we have a valid access token."""
        if not self.access_token or not self.token_expires_at:
            return await self._authenticate()
            
        # Refresh token if it expires within 5 minutes
        if datetime.now() >= (self.token_expires_at - timedelta(minutes=5)):
            return await self._refresh_access_token()
            
        return True

    async def _request(self, method: str, endpoint: str, params: dict = None, data: dict | list = None) -> dict[str, Any]:
        """Make a request to the API."""
        if not await self._ensure_valid_token():
            raise Exception("Failed to authenticate with Garo Entity API")
            
        url = f"{self.api_base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        _LOGGER.debug("Making %s request to %s", method, url)
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with asyncio.timeout(30):
                    # Use data as JSON if provided, otherwise use params
                    request_kwargs = {"headers": headers}
                    if data:
                        request_kwargs["json"] = data
                    elif params:
                        request_kwargs["params"] = params
                        
                    async with session.request(method, url, **request_kwargs) as response:
                        _LOGGER.debug("Response status: %s", response.status)
                        _LOGGER.debug("Response headers: %s", dict(response.headers))
                        
                        # Read response content first
                        response_text = await response.text()
                        # Don't log response content as it may contain sensitive data
                        _LOGGER.debug("Response received, length: %s chars", len(response_text))
                        
                        if response.status >= 400:
                            _LOGGER.error(
                                "API request failed with status %s for %s %s", 
                                response.status, method, url
                            )
                        
                        response.raise_for_status()
                        
                        # Try to parse JSON
                        try:
                            data = await response.json()
                            _LOGGER.debug("Successfully parsed JSON response")
                            return data
                        except Exception as json_exc:
                            _LOGGER.error("Failed to parse JSON response: %s", json_exc)
                            # Return raw text if JSON parsing fails
                            return {"raw_response": response_text}
                            
        except Exception as exc:
            _LOGGER.error("API request failed for %s %s: %s", method, url, exc)
            raise

    async def test_connection(self) -> bool:
        """Test the connection to the API."""
        try:
            # Try to get charging stations with limit 1 to test connection
            await self._request("GET", "/charging-stations", {
                "context": "Owner", 
                "limit": 1, 
                "include_relationships": "true"
            })
            return True
        except Exception as exc:
            _LOGGER.error("Connection test failed: %s", exc)
            raise

    async def get_charging_stations(self) -> dict[str, Any]:
        """Get all charging stations."""
        _LOGGER.debug("Requesting charging stations from API")
        response = await self._request("GET", "/charging-stations", {
            "context": "Owner", 
            "include_relationships": "true"
        })
        _LOGGER.debug("Charging stations response type: %s", type(response))
        return response

    async def get_charging_stations_count(self) -> int:
        """Get the count of charging stations."""
        try:
            _LOGGER.debug("Getting charging stations count")
            # Get all charging stations and count them
            response = await self.get_charging_stations()
            
            _LOGGER.debug("Processing charging stations response: %s", response)
            
            # The response should contain an items array with charging stations
            if isinstance(response, dict) and 'items' in response:
                count = len(response['items'])
                _LOGGER.debug("Found %s charging stations in 'items' field", count)
                return count
            elif isinstance(response, dict) and 'data' in response:
                count = len(response['data'])
                _LOGGER.debug("Found %s charging stations in 'data' field", count)
                return count
            elif isinstance(response, list):
                count = len(response)
                _LOGGER.debug("Found %s charging stations in list response", count)
                return count
            else:
                _LOGGER.warning("Unexpected charging stations response format: %s", response)
                _LOGGER.warning("Response type: %s", type(response))
                return 0
                
        except Exception as exc:
            _LOGGER.error("Failed to get charging stations count: %s", exc)
            import traceback            
            _LOGGER.error("Full traceback: %s", traceback.format_exc())
            return 0

    async def get_charging_stations_with_details(self) -> list[dict[str, Any]]:
        """Get charging stations and filter for non-load interface stations."""
        try:
            response = await self.get_charging_stations()
            
            if isinstance(response, dict) and 'items' in response:
                stations = response['items']
                # Filter for stations with load_interface = false
                non_load_interface_stations = [
                    station for station in stations 
                    if not station.get('load_interface', True)
                ]
                _LOGGER.debug("Found %s non-load interface stations out of %s total", 
                            len(non_load_interface_stations), len(stations))
                return non_load_interface_stations
            else:
                _LOGGER.warning("Unexpected charging stations response format: %s", response)
                return []
                
        except Exception as exc:
            _LOGGER.error("Failed to get charging stations with details: %s", exc)
            return []

    async def get_meter_values(self, charging_station_id: str, connector_id: int = 1) -> dict[str, Any]:
        """Get meter values for a specific charging station."""
        _LOGGER.debug("Getting meter values for charging station: %s", charging_station_id)
        try:
            # First trigger meter values collection
            await self.trigger_meter_values(charging_station_id, connector_id)
            
            # Poll until Current.Offered measure appears
            current_offered_found = await self.poll_for_current_offered(charging_station_id, connector_id)
            
            if not current_offered_found:
                _LOGGER.warning("Current.Offered measure not found for station %s after polling", charging_station_id)
            
            # Get the latest meter values
            params = {
                "context": "Owner",
                "charging_station_id": charging_station_id,
                "connector_id": connector_id
            }
            response = await self._request("GET", "/meter-values/latest", params)
            _LOGGER.debug("Meter values response for %s: %s", charging_station_id, response)
            return response
        except Exception as exc:
            _LOGGER.error("Failed to get meter values for station %s: %s", charging_station_id, exc)
            raise

    async def get_all_meter_values(self) -> dict[str, dict[str, Any]]:
        """Get meter values for all non-load interface charging stations."""
        _LOGGER.debug("Getting meter values for all charging stations")
        all_meter_values = {}
        
        try:
            stations = await self.get_charging_stations_with_details()
            
            for station in stations:
                station_id = station['id']
                station_name = station.get('name', station.get('uid', station_id))
                
                try:
                    meter_values = await self.get_meter_values(station_id, connector_id=1)
                    all_meter_values[station_id] = {
                        'station_info': station,
                        'meter_values': meter_values
                    }
                    _LOGGER.debug("Got meter values for station %s (%s)", station_name, station_id)
                except Exception as exc:
                    _LOGGER.error("Failed to get meter values for station %s (%s): %s", 
                                station_name, station_id, exc)
                    continue
                    
            _LOGGER.debug("Retrieved meter values for %s stations", len(all_meter_values))
            return all_meter_values
            
        except Exception as exc:
            _LOGGER.error("Failed to get all meter values: %s", exc)
            return {}

    async def get_connector_status(self, charging_station_id: str) -> dict[str, Any]:
        """Get connector status for a specific charging station."""
        _LOGGER.debug("Getting connector status for charging station: %s", charging_station_id)
        try:
            params = {
                "context": "Owner",
                "charging_station_id": charging_station_id
            }
            response = await self._request("GET", f"/charging-stations/{charging_station_id}/connector-status", params)
            _LOGGER.debug("Connector status response for %s: %s", charging_station_id, response)
            return response
        except Exception as exc:
            _LOGGER.error("Failed to get connector status for station %s: %s", charging_station_id, exc)
            raise

    async def get_all_connector_statuses(self) -> dict[str, dict[str, Any]]:
        """Get connector status for all non-load interface charging stations."""
        _LOGGER.debug("Getting connector statuses for all charging stations")
        all_connector_statuses = {}
        
        try:
            stations = await self.get_charging_stations_with_details()
            
            for station in stations:
                station_id = station['id']
                station_name = station.get('name', station.get('uid', station_id))
                
                try:
                    connector_status = await self.get_connector_status(station_id)
                    all_connector_statuses[station_id] = {
                        'station_info': station,
                        'connector_status': connector_status
                    }
                    _LOGGER.debug("Got connector status for station %s (%s)", station_name, station_id)
                except Exception as exc:
                    _LOGGER.error("Failed to get connector status for station %s (%s): %s", 
                                station_name, station_id, exc)
                    continue
                    
            _LOGGER.debug("Retrieved connector statuses for %s stations", len(all_connector_statuses))
            return all_connector_statuses
            
        except Exception as exc:
            _LOGGER.error("Failed to get all connector statuses: %s", exc)
            return {}

    async def get_charging_station_configuration(self, charging_station_id: str) -> dict[str, Any]:
        """Get configuration values for a specific charging station."""
        _LOGGER.debug("Getting configuration for charging station: %s", charging_station_id)
        try:
            response = await self._request("GET", f"/charging-stations/{charging_station_id}/configuration")
            _LOGGER.debug("Configuration response for %s: %s", charging_station_id, response)
            return response
        except Exception as exc:
            _LOGGER.error("Failed to get configuration for station %s: %s", charging_station_id, exc)
            raise

    async def get_all_charging_station_configurations(self) -> dict[str, dict[str, Any]]:
        """Get configuration values for all non-load interface charging stations."""
        _LOGGER.debug("Getting configurations for all charging stations")
        all_configurations = {}
        
        try:
            stations = await self.get_charging_stations_with_details()
            
            for station in stations:
                station_id = station['id']
                station_name = station.get('name', station.get('uid', station_id))
                
                try:
                    configuration = await self.get_charging_station_configuration(station_id)
                    all_configurations[station_id] = {
                        'station_info': station,
                        'configuration': configuration
                    }
                    _LOGGER.debug("Got configuration for station %s (%s)", station_name, station_id)
                except Exception as exc:
                    _LOGGER.error("Failed to get configuration for station %s (%s): %s", 
                                station_name, station_id, exc)
                    continue
                    
            _LOGGER.debug("Retrieved configurations for %s stations", len(all_configurations))
            return all_configurations
            
        except Exception as exc:
            _LOGGER.error("Failed to get all configurations: %s", exc)
            return {}

    async def set_charging_station_configuration(self, charging_station_id: str, key: str, value: str | int | float | bool) -> dict[str, Any]:
        """Set a configuration value for a specific charging station."""
        _LOGGER.info("Setting configuration %s=%s (%s) for charging station: %s", key, value, type(value).__name__, charging_station_id)
        try:
            # Convert value to string as API expects
            str_value = str(value).lower() if isinstance(value, bool) else str(value)
            
            data = {
                "configuration_variables": [
                    {
                        "key": key,
                        "value": str_value
                    }
                ]
            }
            
            _LOGGER.debug("Sending PUT request to change-configuration endpoint")
            
            response = await self._request("PUT", f"/actions/change-configuration/{charging_station_id}", data=data)
            
            # Check if the configuration change was accepted
            if isinstance(response, dict) and "status" in response:
                status_info = response["status"]
                if isinstance(status_info, dict) and key in status_info:
                    config_status = status_info[key]
                    if config_status == "Accepted":
                        _LOGGER.info("Configuration update accepted for %s %s=%s", charging_station_id, key, str_value)
                    elif config_status == "Rejected":
                        _LOGGER.error("Configuration update rejected for %s %s=%s", charging_station_id, key, str_value)
                        raise Exception(f"Configuration change rejected by charging station: {key}={str_value}")
                    else:
                        _LOGGER.warning("Unknown configuration status '%s' for %s %s=%s", config_status, charging_station_id, key, str_value)
                else:
                    _LOGGER.warning("Configuration key '%s' not found in response status for station %s", key, charging_station_id)
            else:
                _LOGGER.warning("Unexpected response format for configuration change: missing 'status' field")
            
            return response
        except Exception as exc:
            _LOGGER.error("Failed to set configuration %s=%s for station %s: %s", key, value, charging_station_id, exc)
            raise

    async def get_transactions(self, charging_station_id: str, connector_id: int = 1) -> dict[str, Any]:
        """Get transactions for a specific charging station and connector."""
        _LOGGER.debug("Getting transactions for charging station: %s, connector: %s", charging_station_id, connector_id)
        try:
            params = {
                "context": "Owner",
                "charging_station_id": charging_station_id,
                "connector_id": connector_id
            }
            response = await self._request("GET", "/transactions", params)
            _LOGGER.debug("Transactions response for %s: %s", charging_station_id, response)
            return response
        except Exception as exc:
            _LOGGER.error("Failed to get transactions for station %s: %s", charging_station_id, exc)
            raise

    async def get_all_transactions(self) -> dict[str, dict[str, Any]]:
        """Get transactions for all non-load interface charging stations."""
        _LOGGER.debug("Getting transactions for all charging stations")
        all_transactions = {}
        
        try:
            stations = await self.get_charging_stations_with_details()
            
            for station in stations:
                station_id = station['id']
                station_name = station.get('name', station.get('uid', station_id))
                
                try:
                    transactions = await self.get_transactions(station_id, connector_id=1)
                    all_transactions[station_id] = {
                        'station_info': station,
                        'transactions': transactions
                    }
                    _LOGGER.debug("Got transactions for station %s (%s)", station_name, station_id)
                except Exception as exc:
                    _LOGGER.error("Failed to get transactions for station %s (%s): %s", 
                                station_name, station_id, exc)
                    continue
                    
            _LOGGER.debug("Retrieved transactions for %s stations", len(all_transactions))
            return all_transactions
            
        except Exception as exc:
            _LOGGER.error("Failed to get all transactions: %s", exc)
            return {}

    async def trigger_meter_values(self, charging_station_id: str, connector_id: int = 1) -> dict[str, Any]:
        """Trigger meter values collection for a specific charging station and connector."""
        _LOGGER.debug("Triggering meter values for charging station: %s, connector: %s", charging_station_id, connector_id)
        try:
            data = {
                "requested_message": "MeterValues",
                "connector_id": connector_id
            }
            
            response = await self._request("PUT", f"/actions/trigger-message/{charging_station_id}", data=data)
            _LOGGER.debug("Trigger meter values response for %s: %s", charging_station_id, response)
            return response
        except Exception as exc:
            _LOGGER.error("Failed to trigger meter values for station %s: %s", charging_station_id, exc)
            raise

    async def poll_for_current_offered(self, charging_station_id: str, connector_id: int = 1, max_attempts: int = 10, delay: float = 2.0) -> bool:
        """Poll meter values until Current.Offered measure appears."""
        _LOGGER.debug("Polling for Current.Offered measure for station %s, connector %s", charging_station_id, connector_id)
        
        for attempt in range(max_attempts):
            try:
                params = {
                    "context": "Owner",
                    "charging_station_id": charging_station_id,
                    "connector_id": connector_id
                }
                response = await self._request("GET", "/meter-values/latest", params)
                
                # Check if we have measures in the response
                if isinstance(response, dict) and 'measures' in response:
                    measures = response['measures']
                    if isinstance(measures, list):
                        for measure in measures:
                            if isinstance(measure, dict) and measure.get('name') == 'Current.Offered':
                                _LOGGER.debug("Found Current.Offered measure on attempt %s for station %s", attempt + 1, charging_station_id)
                                return True
                
                _LOGGER.debug("Current.Offered not found on attempt %s for station %s, waiting %s seconds", attempt + 1, charging_station_id, delay)
                await asyncio.sleep(delay)
                
            except Exception as exc:
                _LOGGER.warning("Error polling meter values on attempt %s for station %s: %s", attempt + 1, charging_station_id, exc)
                await asyncio.sleep(delay)
        
        _LOGGER.warning("Current.Offered measure not found after %s attempts for station %s", max_attempts, charging_station_id)
        return False

    async def get_user_info_by_id_tokens(self, id_tokens: list[str]) -> dict[str, dict[str, Any]]:
        """Get user information for given ID tokens."""
        if not id_tokens:
            return {}
            
        _LOGGER.debug("Getting user info for %s ID tokens", len(id_tokens))
        all_user_info = {}
        
        # API can only handle one token per call, so make individual requests
        for id_token in id_tokens:
            try:
                params = {
                    "role": "Owner",
                    "id_tokens": id_token  # Single token only
                }
                
                response = await self._request("GET", "/users", params)
                _LOGGER.debug("User info response received for token request")
                
                if isinstance(response, dict):
                    # Merge the response into our result dictionary
                    all_user_info.update(response)
                    
            except Exception as exc:
                _LOGGER.warning("Failed to get user info for token request: %s", exc)
                # Continue with other tokens even if one fails
                continue
        
        _LOGGER.debug("Retrieved user info for %s out of %s tokens", len(all_user_info), len(id_tokens))
        return all_user_info