import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import '../services/valve_control_service.dart';

class ValveControlProvider with ChangeNotifier {
  final ValveControlService _valveService = ValveControlService();

  // Current valve states
  final Map<ValveType, bool> _valveStates = {
    ValveType.valveIn: false,
    ValveType.valveOut: false,  // 修正为 valveOut
    ValveType.valveClean: false,
    ValveType.light: false,
  };

  // Operation status
  bool _isLoading = false;
  String _status = '设备就绪';
  String? _errorMessage;

  // Timer for periodic status updates
  Timer? _statusTimer;

  // Getters
  Map<ValveType, bool> get valveStates => Map.unmodifiable(_valveStates);
  bool get isLoading => _isLoading;
  String get status => _status;
  String? get errorMessage => _errorMessage;

  bool getValveState(ValveType valveType) => _valveStates[valveType] ?? false;

  /// Initialize the valve control provider
  Future<void> initialize() async {
    _setLoading(true);
    try {
      await refreshStatus();
      startStatusUpdates();
    } catch (e) {
      // If initialization fails, still start with default states
      _status = '设备就绪 (状态未知)';
      _setError('初始化时无法获取状态: $e');
      print('Valve control initialization warning: $e');
    } finally {
      _setLoading(false);
    }
  }

  /// Start periodic status updates
  void startStatusUpdates() {
    _statusTimer?.cancel();
    _statusTimer = Timer.periodic(const Duration(seconds: 5), (timer) {
      refreshStatus();
    });
  }

  /// Stop periodic status updates
  void stopStatusUpdates() {
    _statusTimer?.cancel();
    _statusTimer = null;
  }

  /// Control a specific valve/light
  Future<bool> controlValve(ValveType valveType, ValveAction action) async {
    _setLoading(true);
    _clearError();

    try {
      final response = await _valveService.controlValve(valveType, action);
      
      if (response.success) {
        // Update local state
        _valveStates[valveType] = (action == ValveAction.on);
        _status = '${_getValveDisplayName(valveType)} ${action == ValveAction.on ? '已开启' : '已关闭'}';
        
        notifyListeners();
        
        // Refresh status after a short delay to confirm change
        Future.delayed(const Duration(milliseconds: 500), () {
          refreshStatus();
        });
        
        return true;
      } else {
        _setError('控制失败: ${response.message}');
        return false;
      }
    } catch (e) {
      _setError('控制失败: $e');
      return false;
    } finally {
      _setLoading(false);
    }
  }

  /// Toggle a valve/light state
  Future<bool> toggleValve(ValveType valveType) async {
    final currentState = _valveStates[valveType] ?? false;
    final newAction = currentState ? ValveAction.off : ValveAction.on;
    return await controlValve(valveType, newAction);
  }

  /// Refresh valve statuses from server
  Future<void> refreshStatus() async {
    try {
      final response = await _valveService.getValveStatuses();
      
      if (response.success && response.data != null) {
        // Update states based on server response
        for (final valveType in ValveType.values) {
          final serverKey = valveType.apiValue;
          if (response.data!.containsKey(serverKey)) {
            final value = response.data![serverKey];
            // Safe type conversion
            if (value is bool) {
              _valveStates[valveType] = value;
            } else {
              _valveStates[valveType] = false; // Default to false for non-boolean values
            }
          }
        }
        
        _status = '状态已更新';
        _clearError();
        notifyListeners();
      } else {
        // Don't show error for status refresh failures during periodic updates
        if (_errorMessage == null) {
          _status = '设备就绪 (状态未知)';
        }
        print('Failed to refresh valve statuses: ${response.message}');
      }
    } catch (e) {
      // Don't show error for status refresh failures during periodic updates
      if (_errorMessage == null) {
        _status = '设备就绪 (连接中断)';
      }
      print('Error refreshing valve statuses: $e');
    }
  }

  /// Turn off all valves and lights
  Future<bool> turnOffAll() async {
    _setLoading(true);
    _clearError();

    try {
      bool allSuccess = true;
      
      for (final valveType in ValveType.values) {
        if (_valveStates[valveType] == true) {
          final success = await controlValve(valveType, ValveAction.off);
          if (!success) {
            allSuccess = false;
          }
        }
      }
      
      if (allSuccess) {
        _status = '所有设备已关闭';
      } else {
        _setError('部分设备关闭失败');
      }
      
      return allSuccess;
    } catch (e) {
      _setError('关闭所有设备失败: $e');
      return false;
    } finally {
      _setLoading(false);
    }
  }

  /// Set loading state
  void _setLoading(bool loading) {
    _isLoading = loading;
    notifyListeners();
  }

  /// Set error message
  void _setError(String message) {
    _errorMessage = message;
    _status = '错误';
    notifyListeners();
  }

  /// Clear error message
  void _clearError() {
    _errorMessage = null;
  }

  /// Get display name for valve type
  String _getValveDisplayName(ValveType valveType) {
    switch (valveType) {
      case ValveType.valveIn:
        return '进口阀';
      case ValveType.valveOut:  // 修正为 valveOut
        return '出口阀';
      case ValveType.valveClean:
        return '清洗阀';
      case ValveType.light:
        return '光源';
    }
  }

  /// Get display name for valve type (static)
  static String getValveDisplayName(ValveType valveType) {
    switch (valveType) {
      case ValveType.valveIn:
        return '进口阀';
      case ValveType.valveOut:  // 修正为 valveOut
        return '出口阀';
      case ValveType.valveClean:
        return '清洗阀';
      case ValveType.light:
        return '光源';
    }
  }

  /// Get icon for valve type
  static getValveIcon(ValveType valveType) {
    switch (valveType) {
      case ValveType.valveIn:
        return Icons.input;
      case ValveType.valveOut:  // 修正为 valveOut
        return Icons.output;
      case ValveType.valveClean:
        return Icons.cleaning_services;
      case ValveType.light:
        return Icons.lightbulb;
    }
  }

  @override
  void dispose() {
    stopStatusUpdates();
    _valveService.dispose();
    super.dispose();
  }
}
