import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/device_reset.dart';
import '../models/api_response.dart';

/// 设备重置服务
class DeviceResetService {
  static const String baseUrl = 'http://localhost:8000';
  static const Duration timeout = Duration(seconds: 10);

  final http.Client _client = http.Client();

  /// 获取设备模式信息
  Future<ApiResponse<DeviceMode>> getDeviceMode() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/device-mode'))
          .timeout(timeout);

      final responseData = json.decode(response.body);
      
      if (response.statusCode == 200) {
        final apiResponse = ApiResponse.fromJson(
          responseData,
          (json) => DeviceMode.fromJson(json as Map<String, dynamic>),
        );
        return apiResponse;
      } else {
        return ApiResponse<DeviceMode>(
          success: false,
          message: responseData['message'] ?? 'Failed to get device mode',
        );
      }
    } catch (e) {
      return ApiResponse<DeviceMode>(
        success: false,
        message: 'Network error: $e',
      );
    }
  }

  /// 启动设备重置操作
  Future<ApiResponse<DeviceResetResponse>> startDeviceReset({
    required String ip,
    required int register,
    required bool mockMode,
  }) async {
    try {
      final request = DeviceResetRequest(
        ip: ip,
        port: 502, // 固定端口
        register: register,
        mockMode: mockMode,
      );

      final response = await _client
          .post(
            Uri.parse('$baseUrl/hy-device/reset'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode(request.toJson()),
          )
          .timeout(timeout);

      final responseData = json.decode(response.body);
      
      if (response.statusCode == 200) {
        final apiResponse = ApiResponse.fromJson(
          responseData,
          (json) => DeviceResetResponse.fromJson(json as Map<String, dynamic>),
        );
        return apiResponse;
      } else {
        return ApiResponse<DeviceResetResponse>(
          success: false,
          message: responseData['message'] ?? 'Failed to start device reset',
        );
      }
    } catch (e) {
      return ApiResponse<DeviceResetResponse>(
        success: false,
        message: 'Network error: $e',
      );
    }
  }

  /// 查询设备重置状态
  Future<ApiResponse<DeviceResetStatus>> getResetStatus(String taskId) async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/hy-device/reset-status/$taskId'))
          .timeout(timeout);

      final responseData = json.decode(response.body);
      
      if (response.statusCode == 200) {
        final apiResponse = ApiResponse.fromJson(
          responseData,
          (json) => DeviceResetStatus.fromJson(json as Map<String, dynamic>),
        );
        return apiResponse;
      } else {
        return ApiResponse<DeviceResetStatus>(
          success: false,
          message: responseData['message'] ?? 'Failed to get reset status',
        );
      }
    } catch (e) {
      return ApiResponse<DeviceResetStatus>(
        success: false,
        message: 'Network error: $e',
      );
    }
  }

  void dispose() {
    _client.close();
  }
}
