import '../models/api_response.dart';
import 'api_service.dart';

enum ValveType {
  valveIn('VALVE_IN'),
  valveOut('VALVE_OUT'),  // 修正为 VALVE_OUT 而不是 VALVE_OFF
  valveClean('VALVE_CLEAN'),
  light('LIGHT');

  const ValveType(this.apiValue);
  final String apiValue;
}

enum ValveAction {
  on('ON'),
  off('OFF');

  const ValveAction(this.apiValue);
  final String apiValue;
}

class ValveControlService {
  final ApiService _apiService = ApiService();

  /// Control valve/light switch
  Future<ApiResponse<Map<String, dynamic>>> controlValve(
    ValveType valveType,
    ValveAction action,
  ) async {
    return await _apiService.controlValve(valveType.apiValue, action.apiValue);
  }

  /// Get current valve statuses
  Future<ApiResponse<Map<String, dynamic>>> getValveStatuses() async {
    return await _apiService.getValveStatuses();
  }

  void dispose() {
    _apiService.dispose();
  }
}
