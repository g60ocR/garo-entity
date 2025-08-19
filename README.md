# Garo Entity Home Assistant Integration

A comprehensive Home Assistant integration for Garo Entity charging stations, providing real-time monitoring and control of your EV charging infrastructure through the Garo CSMS Cloud API.

## Features

### 📊 Comprehensive Monitoring
- **Station Count**: Track total number of charging stations
- **Real-time Meter Values**: Energy consumption, power, current, voltage, frequency, and temperature
- **Connector Status**: Live status of charging connectors
- **Transaction Data**: Charging session information including energy consumed, start/end times, and user details
- **Station Status**: Connection, registration, installation, and configuration status
- **Hardware Information**: Serial numbers, model information, firmware versions

### 🔋 Sensor Types

#### Meter Value Sensors
- Energy Import (kWh)
- Active Power (W) 
- Current Import/Export/Offered (A)
- Voltage (V)
- Frequency (Hz)
- Temperature (°C)

#### Transaction Sensors
- Transaction Status
- Transaction Energy
- Transaction Start Time
- Transaction End Time
- Transaction User (when ID token is available)

#### Station Status Sensors
- Connection Status
- Registration Status
- Installation Status
- Configuration Status
- Firmware Update Status
- Heartbeat Timestamp
- Last Firmware Update Check
- Configuration Sync Required
- Using Proxy

#### Charging Unit Sensors
- Serial Number
- Vendor Name
- Model
- Firmware Version

#### Configuration Sensors
- Light Intensity
- Max Current settings
- Network configuration
- Time zone settings
- And more...

## Requirements

- Home Assistant 2023.1.0 or newer
- Garo Entity Cloud account with **Owner** role access

## Installation

### Manual Installation

1. Download the latest release from the [GitHub repository](https://github.com/g60ocR/garo-entity)
2. Copy the `custom_components/garo_entity` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant

## Configuration

### Prerequisites

⚠️ **Important**: You must have **Owner** role access to your Garo Entity charging stations. The integration will not work with other permission levels.

### Setup

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "Garo Entity"
4. Enter your Garo Entity Cloud credentials:
   - **Username**: Your Garo Connect account username
   - **Password**: Your Garo Connect account password
   - **Cognito Client ID**: (optional, uses default if not specified)
   - **Cognito Region**: (optional, uses default if not specified)  
   - **API Base URL**: (optional, uses default if not specified)

The integration will automatically discover and set up sensors for all your non-load interface charging stations.

## Entity Naming

Entities are named using the following pattern:
- `sensor.{station_name}_{sensor_type}`

Examples:
- `sensor.home_charger_energy_import`
- `sensor.office_connector_1_status`
- `sensor.garage_transaction_status`
- `sensor.driveway_serial_number`

## Advanced Features

### Meter Value Triggering

The integration automatically triggers meter value collection before reading sensor data to ensure fresh information is available from the charging stations.

### User Identification

When charging sessions include ID tokens, the integration automatically fetches user information to display friendly names instead of cryptic tokens.

### Multi-Phase Support

For three-phase charging stations, separate sensors are created for each phase, providing detailed insight into power distribution.

### Error Handling

The integration includes comprehensive error handling and will continue operating even if some data sources are temporarily unavailable.

## Limitations

### Not Yet Implemented
- **Starting/Stopping Charging Sessions**: Remote control of charging sessions is not currently implemented
- **Configuration Changes**: Modifying charging station settings through Home Assistant (except changing the LED light intensity and the max offered ampere)

### API Limitations
- Update interval: 15 minutes (cloud API rate limiting)
- Only non-load interface stations are supported
- Requires stable internet connection

## Troubleshooting

### Common Issues

**Integration fails to load**
- Verify your credentials are correct
- Ensure you have Owner role access to the charging stations
- Check Home Assistant logs for detailed error messages

**No sensors appear**
- Verify your account has access to charging stations
- Check that stations are not load interface type
- Wait for the initial data refresh (up to 15 minutes)

**User names show as tokens**
- User information is only available for charging sessions with ID tokens
- Some sessions may not include user identification
- See "Known API Issues" below for more details on user token limitations

### Debug Logging

To enable debug logging, add this to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.garo_entity: debug
```

## Known API Issues

The Garo CSMS Cloud API has several known limitations and issues that affect the integration's functionality:

### User Information Limitations

**Issue**: Certain ID tokens cause 500 Internal Server Error when querying user information via the `GET /users` endpoint.

**Impact**: 
- Some transactions may display ID tokens instead of user names
- User identification fails for specific token formats or users
- No way to predict which tokens will cause errors

**Workaround**: The integration falls back to displaying the raw ID token when user lookup fails, ensuring transaction data is still available.

### Configuration Mutability Unknown

**Issue**: The API returns `"mutability": null` for all configuration values, making it impossible to determine which settings can be modified.

**Impact**:
- No way to know programmatically which configuration values are read-only
- Users may attempt to change immutable settings and receive rejection errors
- Cannot provide appropriate UI hints about which settings are editable

**Current Approach**: The integration exposes number entities for commonly changeable values (LightIntensity, MaxCurrent settings) based on empirical testing.

### Configuration Endpoint Limitations

**Issue**: The standard `PUT /charging-stations/{id}/configuration` endpoint does not reliably apply configuration changes.

**Root Cause**: Configuration changes appear to require explicit commit/synchronization with the charging station that the standard endpoint doesn't trigger. The load balancer or backend service may not properly propagate changes.

**Solution**: The integration uses `PUT /actions/change-configuration/{id}` instead, which properly handles the commit process and returns explicit "Accepted"/"Rejected" status responses.

### API Rate Limiting

**Note**: The integration uses a 15-minute polling interval to provide reasonable data freshness for EV charging scenarios.

## API Documentation

This integration uses the Garo CSMS Cloud API. For API documentation and support, contact Garo Entity support.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

### Version 1.0.0
- Initial release
- Support for all major sensor types
- Automatic user identification
- Comprehensive error handling
- Multi-phase power monitoring

## Support

For issues and feature requests, please use the [GitHub issue tracker](https://github.com/g60ocR/garo-entity/issues).

## Acknowledgments

- Thanks to Garo for providing the cloud API
- Home Assistant community for integration development guidance
- Claude Code that I used to vibe code this entire thing in a short time