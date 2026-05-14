import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/api_response.dart';
import '../models/spectrum_data.dart';
import '../models/device_config.dart';

class ApiService {
  static const String baseUrl = 'http://localhost:8000';
  static const Duration timeout = Duration(seconds: 10);

  final http.Client _client = http.Client();

  /// Health check
  Future<bool> checkHealth() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/health'))
          .timeout(timeout);
      
      if (response.statusCode == 200) {
        final apiResponse = ApiResponse.fromJson(
          json.decode(response.body),
          (json) => json,
        );
        return apiResponse.success;
      }
      return false;
    } catch (e) {
      print('Health check failed: $e');
      return false;
    }
  }

  /// Set HY device address
  Future<ApiResponse<Map<String, dynamic>>> setDeviceAddress(
      String ip, int port) async {
    try {
      final deviceConfig = DeviceConfig(ip: ip, port: port);
      final response = await _client
          .post(
            Uri.parse('$baseUrl/hy-device/set-address'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode(deviceConfig.toJson()),
          )
          .timeout(timeout);

      return ApiResponse.fromJson(
        json.decode(response.body),
        (json) => json as Map<String, dynamic>,
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to set device address: $e',
      );
    }
  }

  /// Get device settings
  Future<ApiResponse<DeviceConfig>> getDeviceSettings() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/api/settings/device'))
          .timeout(timeout);

      if (response.statusCode == 200) {
        final jsonMap = json.decode(utf8.decode(response.bodyBytes));
        return ApiResponse(
          success: true,
          message: 'Success',
          data: DeviceConfig.fromJson(jsonMap),
        );
      }
      return ApiResponse(success: false, message: 'Failed to load settings: ${response.statusCode}');
    } catch (e) {
      return ApiResponse(success: false, message: 'Error loading settings: $e');
    }
  }

  /// Update device settings
  Future<ApiResponse<void>> updateDeviceSettings(DeviceConfig config) async {
    try {
      final jsonBody = json.encode(config.toJson());
      print('🔍 [Frontend] Sending updateDeviceSettings request: $jsonBody');
      
      final response = await _client
          .post(
            Uri.parse('$baseUrl/api/settings/device'),
            headers: {'Content-Type': 'application/json'},
            body: jsonBody,
          )
          .timeout(timeout);

      print('🔍 [Frontend] updateDeviceSettings response: ${response.statusCode} ${response.body}');

      if (response.statusCode == 200) {
        return ApiResponse(success: true, message: 'Settings updated');
      }
      return ApiResponse(success: false, message: 'Failed to update settings: ${response.statusCode}');
    } catch (e) {
      print('🔍 [Frontend] updateDeviceSettings error: $e');
      return ApiResponse(success: false, message: 'Error updating settings: $e');
    }
  }

  /// Sync spectrum query interval to HY_Online so SPC upload uses the same cadence.
  Future<ApiResponse<void>> updateSpectrumQueryInterval(int seconds) async {
    try {
      final jsonBody = json.encode({
        'spectrum': {'query_interval_sec': seconds},
      });
      final response = await _client
          .post(
            Uri.parse('$baseUrl/api/settings/device'),
            headers: {'Content-Type': 'application/json'},
            body: jsonBody,
          )
          .timeout(timeout);

      if (response.statusCode == 200) {
        return ApiResponse(success: true, message: 'Settings updated');
      }
      return ApiResponse(
        success: false,
        message: 'Failed to update spectrum interval: ${response.statusCode}',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Error updating spectrum interval: $e',
      );
    }
  }

  /// Get available drivers
  Future<ApiResponse<List<String>>> getAvailableDrivers() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/api/settings/drivers'))
          .timeout(timeout);

      if (response.statusCode == 200) {
        final jsonMap = json.decode(utf8.decode(response.bodyBytes));
        final drivers = (jsonMap['drivers'] as List).cast<String>();
        return ApiResponse(
          success: true,
          message: 'Success',
          data: drivers,
        );
      }
      return ApiResponse(success: false, message: 'Failed to load drivers');
    } catch (e) {
      return ApiResponse(success: false, message: 'Error loading drivers: $e');
    }
  }

  /// Get device types
  Future<ApiResponse<List<String>>> getDeviceTypes() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/hy-device/types'))
          .timeout(timeout);

      if (response.statusCode != 200) {
        final errorMessage = _parseErrorResponse(response.body);
        return ApiResponse(
          success: false,
          message: 'Error getting device types: $errorMessage',
        );
      }

      try {
        final responseJson = json.decode(response.body);
        
        if (responseJson is Map<String, dynamic>) {
          if (responseJson.containsKey('success')) {
            // Standard API response format
            final apiResponse = ApiResponse.fromJson(responseJson, (json) => json);
            if (apiResponse.success && apiResponse.data != null) {
              // Handle nested data structure
              if (apiResponse.data is Map<String, dynamic> && 
                  (apiResponse.data as Map<String, dynamic>)['types'] is List) {
                final types = ((apiResponse.data as Map<String, dynamic>)['types'] as List).cast<String>();
                return ApiResponse(
                  success: true,
                  message: apiResponse.message,
                  data: types,
                );
              } else if (apiResponse.data is List) {
                final types = (apiResponse.data as List).cast<String>();
                return ApiResponse(
                  success: true,
                  message: apiResponse.message,
                  data: types,
                );
              }
            }
            return ApiResponse(
              success: false,
              message: apiResponse.message,
            );
          } else if (responseJson.containsKey('types')) {
            // Direct response with types field
            final types = (responseJson['types'] as List).cast<String>();
            return ApiResponse(
              success: true,
              message: 'Device types retrieved successfully',
              data: types,
            );
          }
        } else if (responseJson is List) {
          // Direct list response
          final types = (responseJson as List).cast<String>();
          return ApiResponse(
            success: true,
            message: 'Device types retrieved successfully',
            data: types,
          );
        }
        
        return ApiResponse(
          success: false,
          message: 'Unexpected response format for device types',
        );
      } catch (e) {
        return ApiResponse(
          success: false,
          message: 'Failed to parse device types response: $e',
        );
      }
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to get device types: $e',
      );
    }
  }

  /// Query sensor data
  Future<ApiResponse<double>> querySensorData(String deviceType) async {
    try {
      final response = await _client
          .post(
            Uri.parse('$baseUrl/hy-device/query'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode({'device_type': deviceType}),
          )
          .timeout(timeout);

      if (response.statusCode != 200) {
        final errorMessage = _parseErrorResponse(response.body);
        return ApiResponse(
          success: false,
          message: 'Error querying sensor data: $errorMessage',
        );
      }

      final responseJson = json.decode(response.body);
      
      if (responseJson is Map<String, dynamic>) {
        final apiResponse = ApiResponse.fromJson(responseJson, (json) => json);
        
        if (apiResponse.success && apiResponse.data != null) {
          // Extract the value from the data object
          if (apiResponse.data is Map<String, dynamic>) {
            final dataMap = apiResponse.data as Map<String, dynamic>;
            if (dataMap.containsKey('value') && dataMap['value'] is num) {
              final value = (dataMap['value'] as num).toDouble();
              return ApiResponse(
                success: true,
                message: apiResponse.message,
                data: value,
              );
            }
          }
        }
        
        return ApiResponse(
          success: false,
          message: apiResponse.message.isNotEmpty ? apiResponse.message : 'Failed to extract sensor value',
        );
      }
      
      return ApiResponse(
        success: false,
        message: 'Unexpected response format for sensor query',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to query sensor data: $e',
      );
    }
  }

  /// Get full sensor + bridge snapshot (DDL/PH/PH_TEMP/PT100/valves/alarm/fan
  /// 以及来自 hy_server.BridgeDataManager 的 temperature/level/bridge_state/...)
  Future<ApiResponse<Map<String, dynamic>>> getSensorsSnapshot() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/hy-device/sensors'))
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) {
          if (json is Map) {
            return Map<String, dynamic>.from(json);
          }
          return <String, dynamic>{};
        },
        '/hy-device/sensors',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to get sensors snapshot: $e',
        data: <String, dynamic>{},
      );
    }
  }

  /// Test device connection
  Future<ApiResponse<bool>> testDeviceConnection() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/hy-device/test-connection'))
          .timeout(timeout);

      return ApiResponse.fromJson(
        json.decode(response.body),
        (json) => json as bool,
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to test device connection: $e',
      );
    }
  }

  /// Initialize CDS350 device
  Future<ApiResponse<Map<String, dynamic>>> initializeCDS350() async {
    try {
      final response = await _client
          .post(Uri.parse('$baseUrl/cds350/initialize'))
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) => json as Map<String, dynamic>,
        '/cds350/initialize',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to initialize CDS350: $e',
        data: <String, dynamic>{},
      );
    }
  }

  /// Configure CDS350 device
  Future<ApiResponse<Map<String, dynamic>>> configureCDS350(
      CDS350Config config) async {
    try {
      final response = await _client
          .post(
            Uri.parse('$baseUrl/cds350/configure'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode(config.toJson()),
          )
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) => json as Map<String, dynamic>,
        '/cds350/configure',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to configure CDS350: $e',
        data: <String, dynamic>{},
      );
    }
  }

  /// Get spectrum data from CDS350
  Future<ApiResponse<SpectrumData>> getSpectrumData() async {
    try {
      String url = '$baseUrl/cds350/spectrum';
      
      final response = await _client
          .get(Uri.parse(url))
          .timeout(timeout);

      if (response.statusCode != 200) {
        final errorMessage = _parseErrorResponse(response.body);
        return ApiResponse(
          success: false,
          message: 'Error getting spectrum data: $errorMessage',
        );
      }

      try {
        final responseJson = json.decode(response.body);
        Map<String, dynamic> spectrumDataJson;

        // Handle different response formats
        if (responseJson is Map<String, dynamic>) {
          if (responseJson.containsKey('success')) {
            // Standard API response format
            final apiResponse = ApiResponse.fromJson(
              responseJson,
              (json) => json as Map<String, dynamic>,
            );
            if (!apiResponse.success || apiResponse.data == null) {
              return ApiResponse(
                success: false,
                message: apiResponse.message,
              );
            }
            spectrumDataJson = apiResponse.data!;
          } else {
            // Direct spectrum data
            spectrumDataJson = responseJson;
          }
        } else {
          return ApiResponse(
            success: false,
            message: 'Invalid response format from spectrum endpoint',
          );
        }

        // Handle missing or null data gracefully and map correct field names
        List<double> wavelengths;
        List<int> intensities;
        
        if (spectrumDataJson['wavelengths'] != null) {
          wavelengths = (spectrumDataJson['wavelengths'] as List)
              .map((e) => (e as num).toDouble())
              .toList();
        } else {
          return ApiResponse(
            success: false,
            message: 'Spectrum data missing wavelengths. Available keys: ${spectrumDataJson.keys.toList()}',
          );
        }
        
        // The backend uses 'spectrum' field for intensities, not 'intensities'
        if (spectrumDataJson['spectrum'] != null) {
          intensities = (spectrumDataJson['spectrum'] as List)
              .map((e) => (e as num).toInt())
              .toList();
        } else if (spectrumDataJson['intensities'] != null) {
          // Fallback to 'intensities' field if available
          intensities = (spectrumDataJson['intensities'] as List)
              .map((e) => (e as num).toInt())
              .toList();
        } else {
          return ApiResponse(
            success: false,
            message: 'Spectrum data missing intensities/spectrum field. Available keys: ${spectrumDataJson.keys.toList()}',
          );
        }

        // 调试信息：打印API返回的完整数据
        print('🔍 [API Debug] Full response JSON: ${json.encode(spectrumDataJson)}');
        print('🔍 [API Debug] acquisition_time: ${spectrumDataJson['acquisition_time']}');
        print('🔍 [API Debug] last_acquisition_time: ${spectrumDataJson['last_acquisition_time']}');
        print('🔍 [API Debug] integration_time: ${spectrumDataJson['integration_time']}');
        print('🔍 [API Debug] scans_to_average: ${spectrumDataJson['scans_to_average']}');
        print('🔍 [API Debug] acquisition_status: ${spectrumDataJson['acquisition_status']}');
        print('🔍 [API Debug] success: ${spectrumDataJson['success']}');
        print('🔍 [API Debug] message: ${spectrumDataJson['message']}');
        print('🔍 [API Debug] data: ${spectrumDataJson['data']}');
        print('🔍 [API Debug] status: ${spectrumDataJson['status']}');
        print('🔍 [API Debug] error: ${spectrumDataJson['error']}');
        print('🔍 [API Debug] stack: ${spectrumDataJson['stack']}');
        print('🔍 [API Debug] timestamp: ${spectrumDataJson['timestamp']}');
        print('🔍 [API Debug] last_modified: ${spectrumDataJson['last_modified']}');
        print('🔍 [API Debug] created_at: ${spectrumDataJson['created_at']}');
        print('🔍 [API Debug] updated_at: ${spectrumDataJson['updated_at']}');
        print('🔍 [API Debug] __v: ${spectrumDataJson['__v']}');
        print('🔍 [API Debug] id: ${spectrumDataJson['_id']}');
        print('🔍 [API Debug] device_id: ${spectrumDataJson['device_id']}');
        print('🔍 [API Debug] user_id: ${spectrumDataJson['user_id']}');
        print('🔍 [API Debug] role: ${spectrumDataJson['role']}');
        print('🔍 [API Debug] permissions: ${spectrumDataJson['permissions']}');
        print('🔍 [API Debug] ip: ${spectrumDataJson['ip']}');
        print('🔍 [API Debug] port: ${spectrumDataJson['port']}');
        print('🔍 [API Debug] protocol: ${spectrumDataJson['protocol']}');
        print('🔍 [API Debug] baudrate: ${spectrumDataJson['baudrate']}');
        print('🔍 [API Debug] databits: ${spectrumDataJson['databits']}');
        print('🔍 [API Debug] stopbits: ${spectrumDataJson['stopbits']}');
        print('🔍 [API Debug] parity: ${spectrumDataJson['parity']}');
        print('🔍 [API Debug] flowcontrol: ${spectrumDataJson['flowcontrol']}');
        print('🔍 [API Debug] timeout: ${spectrumDataJson['timeout']}');
        print('🔍 [API Debug] retries: ${spectrumDataJson['retries']}');
        print('🔍 [API Debug] delay: ${spectrumDataJson['delay']}');
        print('🔍 [API Debug] max_attempts: ${spectrumDataJson['max_attempts']}');
        print('🔍 [API Debug] min_wavelength: ${spectrumDataJson['min_wavelength']}');
        print('🔍 [API Debug] max_wavelength: ${spectrumDataJson['max_wavelength']}');
        print('🔍 [API Debug] min_intensity: ${spectrumDataJson['min_intensity']}');
        print('🔍 [API Debug] max_intensity: ${spectrumDataJson['max_intensity']}');
        print('🔍 [API Debug] gain: ${spectrumDataJson['gain']}');
        print('🔍 [API Debug] offset: ${spectrumDataJson['offset']}');
        print('🔍 [API Debug] exposure: ${spectrumDataJson['exposure']}');
        print('🔍 [API Debug] brightness: ${spectrumDataJson['brightness']}');
        print('🔍 [API Debug] contrast: ${spectrumDataJson['contrast']}');
        print('🔍 [API Debug] saturation: ${spectrumDataJson['saturation']}');
        print('🔍 [API Debug] hue: ${spectrumDataJson['hue']}');
        print('🔍 [API Debug] sharpness: ${spectrumDataJson['sharpness']}');
        print('🔍 [API Debug] gamma: ${spectrumDataJson['gamma']}');
        print('🔍 [API Debug] white_balance: ${spectrumDataJson['white_balance']}');
        print('🔍 [API Debug] black_level: ${spectrumDataJson['black_level']}');
        print('🔍 [API Debug] white_level: ${spectrumDataJson['white_level']}');
        print('🔍 [API Debug] auto_exposure: ${spectrumDataJson['auto_exposure']}');
        print('🔍 [API Debug] auto_white_balance: ${spectrumDataJson['auto_white_balance']}');
        print('🔍 [API Debug] auto_focus: ${spectrumDataJson['auto_focus']}');
        print('🔍 [API Debug] focus_mode: ${spectrumDataJson['focus_mode']}');
        print('🔍 [API Debug] iris: ${spectrumDataJson['iris']}');
        print('🔍 [API Debug] shutter: ${spectrumDataJson['shutter']}');
        print('🔍 [API Debug] led_power: ${spectrumDataJson['led_power']}');
        print('🔍 [API Debug] laser_power: ${spectrumDataJson['laser_power']}');
        print('🔍 [API Debug] lamp_power: ${spectrumDataJson['lamp_power']}');
        print('🔍 [API Debug] fan_speed: ${spectrumDataJson['fan_speed']}');
        print('🔍 [API Debug] heater_temperature: ${spectrumDataJson['heater_temperature']}');
        print('🔍 [API Debug] cooler_temperature: ${spectrumDataJson['cooler_temperature']}');
        print('🔍 [API Debug] pressure: ${spectrumDataJson['pressure']}');
        print('🔍 [API Debug] humidity: ${spectrumDataJson['humidity']}');
        print('🔍 [API Debug] temperature: ${spectrumDataJson['temperature']}');
        print('🔍 [API Debug] voltage: ${spectrumDataJson['voltage']}');
        print('🔍 [API Debug] current: ${spectrumDataJson['current']}');
        print('🔍 [API Debug] power: ${spectrumDataJson['power']}');
        print('🔍 [API Debug] energy: ${spectrumDataJson['energy']}');
        print('🔍 [API Debug] frequency: ${spectrumDataJson['frequency']}');
        print('🔍 [API Debug] phase: ${spectrumDataJson['phase']}');
        print('🔍 [API Debug] duty_cycle: ${spectrumDataJson['duty_cycle']}');
        print('🔍 [API Debug] pulse_width: ${spectrumDataJson['pulse_width']}');
        print('🔍 [API Debug] pulse_delay: ${spectrumDataJson['pulse_delay']}');
        print('🔍 [API Debug] pulse_repeats: ${spectrumDataJson['pulse_repeats']}');
        print('🔍 [API Debug] pulse_interval: ${spectrumDataJson['pulse_interval']}');
        print('🔍 [API Debug] pulse_duration: ${spectrumDataJson['pulse_duration']}');
        print('🔍 [API Debug] pulse_amplitude: ${spectrumDataJson['pulse_amplitude']}');
        print('🔍 [API Debug] pulse_offset: ${spectrumDataJson['pulse_offset']}');
        print('🔍 [API Debug] pulse_shape: ${spectrumDataJson['pulse_shape']}');
        print('🔍 [API Debug] pulse_polarity: ${spectrumDataJson['pulse_polarity']}');
        print('🔍 [API Debug] pulse_sync: ${spectrumDataJson['pulse_sync']}');
        print('🔍 [API Debug] pulse_trigger: ${spectrumDataJson['pulse_trigger']}');
        print('🔍 [API Debug] pulse_mode: ${spectrumDataJson['pulse_mode']}');
        print('🔍 [API Debug] pulse_source: ${spectrumDataJson['pulse_source']}');
        print('🔍 [API Debug] pulse_destination: ${spectrumDataJson['pulse_destination']}');
        print('🔍 [API Debug] pulse_channel: ${spectrumDataJson['pulse_channel']}');
        print('🔍 [API Debug] pulse_index: ${spectrumDataJson['pulse_index']}');
        print('🔍 [API Debug] pulse_count: ${spectrumDataJson['pulse_count']}');
        print('🔍 [API Debug] pulse_limit: ${spectrumDataJson['pulse_limit']}');
        print('🔍 [API Debug] pulse_timeout: ${spectrumDataJson['pulse_timeout']}');
        print('🔍 [API Debug] pulse_interval_ms: ${spectrumDataJson['pulse_interval_ms']}');
        print('🔍 [API Debug] pulse_duration_ms: ${spectrumDataJson['pulse_duration_ms']}');
        print('🔍 [API Debug] pulse_amplitude_mv: ${spectrumDataJson['pulse_amplitude_mv']}');
        print('🔍 [API Debug] pulse_offset_mv: ${spectrumDataJson['pulse_offset_mv']}');
        print('🔍 [API Debug] pulse_shape_type: ${spectrumDataJson['pulse_shape_type']}');
        print('🔍 [API Debug] pulse_polarity_type: ${spectrumDataJson['pulse_polarity_type']}');
        print('🔍 [API Debug] pulse_sync_type: ${spectrumDataJson['pulse_sync_type']}');
        print('🔍 [API Debug] pulse_trigger_type: ${spectrumDataJson['pulse_trigger_type']}');
        print('🔍 [API Debug] pulse_mode_type: ${spectrumDataJson['pulse_mode_type']}');
        print('🔍 [API Debug] pulse_source_type: ${spectrumDataJson['pulse_source_type']}');
        print('🔍 [API Debug] pulse_destination_type: ${spectrumDataJson['pulse_destination_type']}');
        print('🔍 [API Debug] pulse_channel_type: ${spectrumDataJson['pulse_channel_type']}');
        print('🔍 [API Debug] pulse_index_type: ${spectrumDataJson['pulse_index_type']}');
        print('🔍 [API Debug] pulse_count_type: ${spectrumDataJson['pulse_count_type']}');
        print('🔍 [API Debug] pulse_limit_type: ${spectrumDataJson['pulse_limit_type']}');
        print('🔍 [API Debug] pulse_timeout_type: ${spectrumDataJson['pulse_timeout_type']}');
        print('🔍 [API Debug] pulse_interval_ms_type: ${spectrumDataJson['pulse_interval_ms_type']}');
        print('🔍 [API Debug] pulse_duration_ms_type: ${spectrumDataJson['pulse_duration_ms_type']}');
        print('🔍 [API Debug] pulse_amplitude_mv_type: ${spectrumDataJson['pulse_amplitude_mv_type']}');
        print('🔍 [API Debug] pulse_offset_mv_type: ${spectrumDataJson['pulse_offset_mv_type']}');
        print('🔍 [API Debug] __type: ${spectrumDataJson['__type']}');
        print('🔍 [API Debug] __v: ${spectrumDataJson['__v']}');
        print('🔍 [API Debug] _id: ${spectrumDataJson['_id']}');
        print('🔍 [API Debug] device_id: ${spectrumDataJson['device_id']}');
        print('🔍 [API Debug] user_id: ${spectrumDataJson['user_id']}');
        print('🔍 [API Debug] role: ${spectrumDataJson['role']}');
        print('🔍 [API Debug] permissions: ${spectrumDataJson['permissions']}');
        print('🔍 [API Debug] ip: ${spectrumDataJson['ip']}');
        print('🔍 [API Debug] port: ${spectrumDataJson['port']}');
        print('🔍 [API Debug] protocol: ${spectrumDataJson['protocol']}');
        print('🔍 [API Debug] baudrate: ${spectrumDataJson['baudrate']}');
        print('🔍 [API Debug] databits: ${spectrumDataJson['databits']}');
        print('🔍 [API Debug] stopbits: ${spectrumDataJson['stopbits']}');
        print('🔍 [API Debug] parity: ${spectrumDataJson['parity']}');
        print('🔍 [API Debug] flowcontrol: ${spectrumDataJson['flowcontrol']}');
        print('🔍 [API Debug] timeout: ${spectrumDataJson['timeout']}');
        print('🔍 [API Debug] retries: ${spectrumDataJson['retries']}');
        print('🔍 [API Debug] delay: ${spectrumDataJson['delay']}');
        print('🔍 [API Debug] max_attempts: ${spectrumDataJson['max_attempts']}');
        print('🔍 [API Debug] min_wavelength: ${spectrumDataJson['min_wavelength']}');
        print('🔍 [API Debug] max_wavelength: ${spectrumDataJson['max_wavelength']}');
        print('🔍 [API Debug] min_intensity: ${spectrumDataJson['min_intensity']}');
        print('🔍 [API Debug] max_intensity: ${spectrumDataJson['max_intensity']}');
        print('🔍 [API Debug] gain: ${spectrumDataJson['gain']}');
        print('🔍 [API Debug] offset: ${spectrumDataJson['offset']}');
        print('🔍 [API Debug] exposure: ${spectrumDataJson['exposure']}');
        print('🔍 [API Debug] brightness: ${spectrumDataJson['brightness']}');
        print('🔍 [API Debug] contrast: ${spectrumDataJson['contrast']}');
        print('🔍 [API Debug] saturation: ${spectrumDataJson['saturation']}');
        print('🔍 [API Debug] hue: ${spectrumDataJson['hue']}');
        print('🔍 [API Debug] sharpness: ${spectrumDataJson['sharpness']}');
        print('🔍 [API Debug] gamma: ${spectrumDataJson['gamma']}');
        print('🔍 [API Debug] white_balance: ${spectrumDataJson['white_balance']}');
        print('🔍 [API Debug] black_level: ${spectrumDataJson['black_level']}');
        print('🔍 [API Debug] white_level: ${spectrumDataJson['white_level']}');
        print('🔍 [API Debug] auto_exposure: ${spectrumDataJson['auto_exposure']}');
        print('🔍 [API Debug] auto_white_balance: ${spectrumDataJson['auto_white_balance']}');
        print('🔍 [API Debug] auto_focus: ${spectrumDataJson['auto_focus']}');
        print('🔍 [API Debug] focus_mode: ${spectrumDataJson['focus_mode']}');
        print('🔍 [API Debug] iris: ${spectrumDataJson['iris']}');
        print('🔍 [API Debug] shutter: ${spectrumDataJson['shutter']}');
        print('🔍 [API Debug] led_power: ${spectrumDataJson['led_power']}');
        print('🔍 [API Debug] laser_power: ${spectrumDataJson['laser_power']}');
        print('🔍 [API Debug] lamp_power: ${spectrumDataJson['lamp_power']}');
        print('🔍 [API Debug] fan_speed: ${spectrumDataJson['fan_speed']}');
        print('🔍 [API Debug] heater_temperature: ${spectrumDataJson['heater_temperature']}');
        print('🔍 [API Debug] cooler_temperature: ${spectrumDataJson['cooler_temperature']}');
        print('🔍 [API Debug] pressure: ${spectrumDataJson['pressure']}');
        print('🔍 [API Debug] humidity: ${spectrumDataJson['humidity']}');
        print('🔍 [API Debug] temperature: ${spectrumDataJson['temperature']}');
        print('🔍 [API Debug] voltage: ${spectrumDataJson['voltage']}');
        print('🔍 [API Debug] current: ${spectrumDataJson['current']}');
        print('🔍 [API Debug] power: ${spectrumDataJson['power']}');
        print('🔍 [API Debug] energy: ${spectrumDataJson['energy']}');
        print('🔍 [API Debug] frequency: ${spectrumDataJson['frequency']}');
        print('🔍 [API Debug] phase: ${spectrumDataJson['phase']}');
        print('🔍 [API Debug] duty_cycle: ${spectrumDataJson['duty_cycle']}');
        print('🔍 [API Debug] pulse_width: ${spectrumDataJson['pulse_width']}');
        print('🔍 [API Debug] pulse_delay: ${spectrumDataJson['pulse_delay']}');
        print('🔍 [API Debug] pulse_repeats: ${spectrumDataJson['pulse_repeats']}');
        print('🔍 [API Debug] pulse_interval: ${spectrumDataJson['pulse_interval']}');
        print('🔍 [API Debug] pulse_duration: ${spectrumDataJson['pulse_duration']}');
        print('🔍 [API Debug] pulse_amplitude: ${spectrumDataJson['pulse_amplitude']}');
        print('🔍 [API Debug] pulse_offset: ${spectrumDataJson['pulse_offset']}');
        print('🔍 [API Debug] pulse_shape: ${spectrumDataJson['pulse_shape']}');
        print('🔍 [API Debug] pulse_polarity: ${spectrumDataJson['pulse_polarity']}');
        print('🔍 [API Debug] pulse_sync: ${spectrumDataJson['pulse_sync']}');
        print('🔍 [API Debug] pulse_trigger: ${spectrumDataJson['pulse_trigger']}');
        print('🔍 [API Debug] pulse_mode: ${spectrumDataJson['pulse_mode']}');
        print('🔍 [API Debug] pulse_source: ${spectrumDataJson['pulse_source']}');
        print('🔍 [API Debug] pulse_destination: ${spectrumDataJson['pulse_destination']}');
        print('🔍 [API Debug] pulse_channel: ${spectrumDataJson['pulse_channel']}');
        print('🔍 [API Debug] pulse_index: ${spectrumDataJson['pulse_index']}');
        print('🔍 [API Debug] pulse_count: ${spectrumDataJson['pulse_count']}');
        print('🔍 [API Debug] pulse_limit: ${spectrumDataJson['pulse_limit']}');
        print('🔍 [API Debug] pulse_timeout: ${spectrumDataJson['pulse_timeout']}');
        print('🔍 [API Debug] pulse_interval_ms: ${spectrumDataJson['pulse_interval_ms']}');
        print('🔍 [API Debug] pulse_duration_ms: ${spectrumDataJson['pulse_duration_ms']}');
        print('🔍 [API Debug] pulse_amplitude_mv: ${spectrumDataJson['pulse_amplitude_mv']}');
        print('🔍 [API Debug] pulse_offset_mv: ${spectrumDataJson['pulse_offset_mv']}');
        print('🔍 [API Debug] pulse_shape_type: ${spectrumDataJson['pulse_shape_type']}');
        print('🔍 [API Debug] pulse_polarity_type: ${spectrumDataJson['pulse_polarity_type']}');
        print('🔍 [API Debug] pulse_sync_type: ${spectrumDataJson['pulse_sync_type']}');
        print('🔍 [API Debug] pulse_trigger_type: ${spectrumDataJson['pulse_trigger_type']}');
        print('🔍 [API Debug] pulse_mode_type: ${spectrumDataJson['pulse_mode_type']}');
        print('🔍 [API Debug] pulse_source_type: ${spectrumDataJson['pulse_source_type']}');
        print('🔍 [API Debug] pulse_destination_type: ${spectrumDataJson['pulse_destination_type']}');
        print('🔍 [API Debug] pulse_channel_type: ${spectrumDataJson['pulse_channel_type']}');
        print('🔍 [API Debug] pulse_index_type: ${spectrumDataJson['pulse_index_type']}');
        print('🔍 [API Debug] pulse_count_type: ${spectrumDataJson['pulse_count_type']}');
        print('🔍 [API Debug] pulse_limit_type: ${spectrumDataJson['pulse_limit_type']}');
        print('🔍 [API Debug] pulse_timeout_type: ${spectrumDataJson['pulse_timeout_type']}');
        print('🔍 [API Debug] pulse_interval_ms_type: ${spectrumDataJson['pulse_interval_ms_type']}');
        print('🔍 [API Debug] pulse_duration_ms_type: ${spectrumDataJson['pulse_duration_ms_type']}');
        print('🔍 [API Debug] pulse_amplitude_mv_type: ${spectrumDataJson['pulse_amplitude_mv_type']}');
        print('🔍 [API Debug] pulse_offset_mv_type: ${spectrumDataJson['pulse_offset_mv_type']}');
        print('🔍 [API Debug] __type: ${spectrumDataJson['__type']}');
        print('🔍 [API Debug] __v: ${spectrumDataJson['__v']}');
        print('🔍 [API Debug] _id: ${spectrumDataJson['_id']}');
        print('🔍 [API Debug] device_id: ${spectrumDataJson['device_id']}');
        print('🔍 [API Debug] user_id: ${spectrumDataJson['user_id']}');
        print('🔍 [API Debug] role: ${spectrumDataJson['role']}');
        print('🔍 [API Debug] permissions: ${spectrumDataJson['permissions']}');
        print('🔍 [API Debug] ip: ${spectrumDataJson['ip']}');
        print('🔍 [API Debug] port: ${spectrumDataJson['port']}');
        print('🔍 [API Debug] protocol: ${spectrumDataJson['protocol']}');
        print('🔍 [API Debug] baudrate: ${spectrumDataJson['baudrate']}');
        print('🔍 [API Debug] databits: ${spectrumDataJson['databits']}');
        print('🔍 [API Debug] stopbits: ${spectrumDataJson['stopbits']}');
        print('🔍 [API Debug] parity: ${spectrumDataJson['parity']}');
        print('🔍 [API Debug] flowcontrol: ${spectrumDataJson['flowcontrol']}');
        print('🔍 [API Debug] timeout: ${spectrumDataJson['timeout']}');
        print('🔍 [API Debug] retries: ${spectrumDataJson['retries']}');
        print('🔍 [API Debug] delay: ${spectrumDataJson['delay']}');
        print('🔍 [API Debug] max_attempts: ${spectrumDataJson['max_attempts']}');
        print('🔍 [API Debug] min_wavelength: ${spectrumDataJson['min_wavelength']}');
        print('🔍 [API Debug] max_wavelength: ${spectrumDataJson['max_wavelength']}');
        print('🔍 [API Debug] min_intensity: ${spectrumDataJson['min_intensity']}');
        print('🔍 [API Debug] max_intensity: ${spectrumDataJson['max_intensity']}');
        print('🔍 [API Debug] gain: ${spectrumDataJson['gain']}');
        print('🔍 [API Debug] offset: ${spectrumDataJson['offset']}');
        print('🔍 [API Debug] exposure: ${spectrumDataJson['exposure']}');
        // ...existing code...
        print('🔍 [API Debug] brightness: ${spectrumDataJson['brightness']}');
        
        return ApiResponse(
          success: true,
          message: 'Success',
          data: SpectrumData.fromJson(spectrumDataJson),
        );
      } catch (parseError) {
          print('🔍 Spectrum parse error: $parseError');
          // print('🔍 Response data: ${responseJson['data']}'); // responseJson might not be available here if decode failed, but it is available in this scope
          return ApiResponse(
            success: false,
            message: 'Failed to parse spectrum data: $parseError',
          );
      }
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to get spectrum: $e',
      );
    }
  }

  /// Control valve
  Future<ApiResponse<Map<String, dynamic>>> controlValve(
      String valveType, String action) async {
    try {
      final response = await _client
          .post(
            Uri.parse('$baseUrl/hy-device/valve-control'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode({'valve_type': valveType, 'action': action}),
          )
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) => json as Map<String, dynamic>,
        '/hy-device/valve-control',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to control valve: $e',
      );
    }
  }

  /// Get valve statuses
  Future<ApiResponse<Map<String, dynamic>>> getValveStatuses() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/hy-device/valve-status'))
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) => json as Map<String, dynamic>,
        '/hy-device/valve-status',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to get valve statuses: $e',
      );
    }
  }

  /// Convert to SPC
  Future<ApiResponse<Map<String, dynamic>>> convertToSpc(
      Map<String, dynamic> spectrumData) async {
    try {
      final response = await _client
          .post(
            Uri.parse('$baseUrl/spc/convert'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode(spectrumData),
          )
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) => json as Map<String, dynamic>,
        '/spc/convert',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to convert to SPC: $e',
      );
    }
  }

  /// Control monitor (start/stop background thread)
  Future<ApiResponse<Map<String, dynamic>>> controlMonitor(String action, {double interval = 2.0}) async {
    try {
      final response = await _client
          .post(
            Uri.parse('$baseUrl/hy-device/monitor/control'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode({
              'action': action,
              'interval': interval,
            }),
          )
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) => json as Map<String, dynamic>,
        '/hy-device/monitor/control',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to control monitor: $e',
      );
    }
  }

  /// Get auto control status
  Future<ApiResponse<Map<String, dynamic>>> getAutoControlStatus() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/auto-control/status'))
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) {
          // Ensure we return a Map<String, dynamic> safely
          if (json is Map) {
            return Map<String, dynamic>.from(json);
          }
          return <String, dynamic>{};
        },
        '/auto-control/status',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to get auto control status: $e',
      );
    }
  }
  
  //----------------------------------------
  /// Start upload relay for both sensor and SPC uploads.
  Future<ApiResponse<Map<String, dynamic>>> startUploadRelay() async {
    try {
      final response = await _client
          .post(Uri.parse('$baseUrl/api/upload-relay/start'))
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) => json is Map<String, dynamic>
            ? json
            : <String, dynamic>{},
        '/api/upload-relay/start',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to start upload relay: $e',
        data: <String, dynamic>{},
      );
    }
  }

  /// Stop upload relay for both sensor and SPC uploads.
  Future<ApiResponse<Map<String, dynamic>>> stopUploadRelay() async {
    try {
      final response = await _client
          .post(Uri.parse('$baseUrl/api/upload-relay/stop'))
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) => json is Map<String, dynamic>
            ? json
            : <String, dynamic>{},
        '/api/upload-relay/stop',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to stop upload relay: $e',
        data: <String, dynamic>{},
      );
    }
  }

  /// Update upload relay state for sensor and/or SPC individually.
  Future<ApiResponse<Map<String, dynamic>>> setUploadRelay({
    bool? uploadSensor,
    bool? uploadSpc,
  }) async {
    if (uploadSensor == null && uploadSpc == null) {
      return ApiResponse(
        success: false,
        message: 'At least one upload relay flag must be provided.',
        data: <String, dynamic>{},
      );
    }

    try {
      final body = <String, dynamic>{};
      if (uploadSensor != null) {
        body['upload_sensor'] = uploadSensor;
      }
      if (uploadSpc != null) {
        body['upload_spc'] = uploadSpc;
      }

      final response = await _client
          .post(
            Uri.parse('$baseUrl/api/upload-relay/set'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode(body),
          )
          .timeout(timeout);

      return _handleApiResponse(
        response,
        (json) => json is Map<String, dynamic>
            ? json
            : <String, dynamic>{},
        '/api/upload-relay/set',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to update upload relay: $e',
        data: <String, dynamic>{},
      );
    }
  }
  //----------------------------------------
  
  /// 开机预热选择：通水 / 跳过
  Future<ApiResponse<bool>> postWarmupChoice({required bool withWater}) async {
    try {
      final response = await _client
          .post(
            Uri.parse('$baseUrl/auto-control/warmup-choice'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode({'with_water': withWater}),
          )
          .timeout(timeout);
      return _handleApiResponse(
        response,
        (_) => true,
        '/auto-control/warmup-choice',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to post warmup choice: $e',
      );
    }
  }

  /// script_define 中 Visible 为真的模式列表
  Future<ApiResponse<List<Map<String, dynamic>>>> getModeUi() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/auto-control/mode-ui'))
          .timeout(timeout);
      return _handleApiResponse(
        response,
        (json) {
          if (json is List) {
            return json
                .map((e) => Map<String, dynamic>.from(e as Map))
                .toList();
          }
          return <Map<String, dynamic>>[];
        },
        '/auto-control/mode-ui',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to get mode UI: $e',
      );
    }
  }

  /// 单次写入模式对应线圈
  Future<ApiResponse<bool>> applyMode(String mode) async {
    try {
      final response = await _client
          .post(
            Uri.parse('$baseUrl/auto-control/apply-mode'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode({'mode': mode}),
          )
          .timeout(timeout);
      return _handleApiResponse(
        response,
        (_) => true,
        '/auto-control/apply-mode',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to apply mode: $e',
      );
    }
  }

  /// define 目录下可选 xlsx
  Future<ApiResponse<List<String>>> getScriptDefineFiles() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/api/settings/script-define-files'))
          .timeout(timeout);
      return _handleApiResponse(
        response,
        (json) {
          if (json is! Map<String, dynamic>) {
            return <String>[];
          }
          final files = json['files'];
          if (files is List) {
            return files.map((e) => e.toString()).toList();
          }
          return <String>[];
        },
        '/api/settings/script-define-files',
      );
    } catch (e) {
      return ApiResponse(
        success: false,
        message: 'Failed to list script define files: $e',
      );
    }
  }

  // Helper methods

  String _parseErrorResponse(String body) {
    try {
      final jsonMap = json.decode(body);
      if (jsonMap is Map<String, dynamic> && jsonMap.containsKey('message')) {
        return jsonMap['message'];
      }
      return body;
    } catch (_) {
      return body;
    }
  }

  ApiResponse<T> _handleApiResponse<T>(
    http.Response response,
    T Function(dynamic) fromJson,
    String endpoint,
  ) {
    if (response.statusCode == 200) {
      try {
        final jsonMap = json.decode(utf8.decode(response.bodyBytes));
        // Check if it's a standard ApiResponse format
        if (jsonMap is Map<String, dynamic> && jsonMap.containsKey('success')) {
           return ApiResponse.fromJson(jsonMap, fromJson);
        }
        // If not, assume the whole body is the data (or wrap it)
        return ApiResponse(
            success: true,
            message: 'Success',
            data: fromJson(jsonMap),
        );
      } catch (e) {
        return ApiResponse(
          success: false,
          message: 'Failed to parse response from $endpoint: $e',
        );
      }
    } else {
      return ApiResponse(
        success: false,
        message: 'Request to $endpoint failed: ${_parseErrorResponse(response.body)}',
      );
    }
  }

  void dispose() {
    _client.close();
  }
}
