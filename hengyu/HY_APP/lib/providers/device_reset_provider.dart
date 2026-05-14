import 'dart:async';
import 'package:flutter/foundation.dart';
import '../models/device_reset.dart';
import '../services/device_reset_service.dart';

/// 设备重置状态枚举
enum ResetState {
  idle,       // 空闲
  resetting,  // 重置中
  completed,  // 完成
  failed,     // 失败
}

/// 设备重置Provider
class DeviceResetProvider with ChangeNotifier {
  final DeviceResetService _resetService = DeviceResetService();

  // 设备模式信息
  DeviceMode? _deviceMode;
  bool _isLoadingMode = false;
  String? _modeError;

  // 重置相关状态
  ResetState _resetState = ResetState.idle;
  String? _currentTaskId;
  DeviceResetStatus? _currentStatus;
  String? _resetError;
  bool _isLoadingReset = false;
  
  // 重置配置
  int _selectedRegister = 0;
  bool _autoResetOnError = false;
  
  // 定时器用于查询重置状态
  Timer? _statusTimer;
  DateTime? _resetStartTime; // 记录重置开始时间
  bool _hasEverGottenStatus = false; // 标记是否曾经成功获取过状态
  
  // 传感器错误计数（用于自动重置）
  int _sensorErrorCount = 0;
  static const int _maxErrorCount = 3;

  // Getters
  DeviceMode? get deviceMode => _deviceMode;
  bool get isLoadingMode => _isLoadingMode;
  String? get modeError => _modeError;
  
  ResetState get resetState => _resetState;
  String? get currentTaskId => _currentTaskId;
  DeviceResetStatus? get currentStatus => _currentStatus;
  String? get resetError => _resetError;
  bool get isLoadingReset => _isLoadingReset;
  
  int get selectedRegister => _selectedRegister;
  bool get autoResetOnError => _autoResetOnError;
  
  int get sensorErrorCount => _sensorErrorCount;
  bool get shouldAutoReset => _autoResetOnError && _sensorErrorCount >= _maxErrorCount;
  
  // 是否正在重置
  bool get isResetting => _resetState == ResetState.resetting;
  
  // 重置进度 (0.0 - 1.0)
  double get resetProgress {
    if (_currentStatus == null || !_currentStatus!.isRunning) return 0.0;
    return _currentStatus!.progress;
  }

  /// 设置选中的寄存器地址
  void setSelectedRegister(int register) {
    if (register >= 0 && register <= 7) {
      _selectedRegister = register;
      notifyListeners();
    }
  }

  /// 设置自动重置开关
  void setAutoResetOnError(bool enabled) {
    _autoResetOnError = enabled;
    notifyListeners();
  }

  /// 增加传感器错误计数
  void incrementSensorErrorCount() {
    _sensorErrorCount++;
    if (kDebugMode) print('Sensor error count: $_sensorErrorCount');
    notifyListeners();
  }

  /// 重置传感器错误计数
  void resetSensorErrorCount() {
    _sensorErrorCount = 0;
    notifyListeners();
  }

  /// 加载设备模式信息
  Future<void> loadDeviceMode() async {
    _isLoadingMode = true;
    _modeError = null;
    notifyListeners();

    try {
      final response = await _resetService.getDeviceMode();
      
      if (response.success && response.data != null) {
        _deviceMode = response.data;
        _modeError = null;
      } else {
        _modeError = response.message;
      }
    } catch (e) {
      _modeError = 'Failed to load device mode: $e';
    }

    _isLoadingMode = false;
    notifyListeners();
  }

  /// 开始设备重置
  Future<bool> startDeviceReset({String? customIp}) async {
    if (_resetState == ResetState.resetting) {
      return false; // 已经在重置中
    }

    _isLoadingReset = true;
    _resetError = null;
    _resetState = ResetState.resetting;
    notifyListeners();

    try {
      // 确保有设备模式信息
      if (_deviceMode == null) {
        await loadDeviceMode();
      }

      if (_deviceMode == null) {
        throw Exception('Failed to get device mode information');
      }

      // 使用传入的IP或默认IP
      final ip = customIp ?? '192.168.1.100';
      
      final response = await _resetService.startDeviceReset(
        ip: ip,
        register: _selectedRegister,
        mockMode: _deviceMode!.isMock,
      );

      if (response.success && response.data != null) {
        _currentTaskId = response.data!.taskId;
        _resetError = null;
        _resetStartTime = DateTime.now(); // 记录重置开始时间
        _hasEverGottenStatus = false; // 重置状态获取标记
        
        // 开始定时查询状态
        _startStatusPolling();
        
        _isLoadingReset = false;
        notifyListeners();
        return true;
      } else {
        _resetState = ResetState.failed;
        _resetError = response.message;
        _isLoadingReset = false;
        notifyListeners();
        return false;
      }
    } catch (e) {
      _resetState = ResetState.failed;
      _resetError = 'Failed to start reset: $e';
      _isLoadingReset = false;
      notifyListeners();
      return false;
    }
  }

  /// 开始状态轮询
  void _startStatusPolling() {
    _statusTimer?.cancel();
    _statusTimer = Timer.periodic(const Duration(seconds: 2), (timer) async {
      await _checkResetStatus();
    });
  }

  /// 检查重置状态
  Future<void> _checkResetStatus() async {
    if (_currentTaskId == null) return;

    // 检查是否超时（根据设备模式设置不同的超时时间）
    if (_resetStartTime != null) {
      final elapsed = DateTime.now().difference(_resetStartTime!);
      final maxDuration = _deviceMode?.isMock == true 
          ? const Duration(seconds: 15)  // 模拟模式最多15秒
          : const Duration(seconds: 90); // 真实模式最多90秒
      
      if (elapsed > maxDuration) {
        if (kDebugMode) print('Reset operation timed out after ${elapsed.inSeconds} seconds');
        _resetState = ResetState.completed; // 假设超时即完成
        _statusTimer?.cancel();
        _statusTimer = null;
        // 重置完成后清零错误计数
        resetSensorErrorCount();
        notifyListeners();
        return;
      }
    }

    try {
      final response = await _resetService.getResetStatus(_currentTaskId!);
      
      if (response.success && response.data != null) {
        _hasEverGottenStatus = true; // 标记已成功获取过状态
        _currentStatus = response.data;
        
        if (_currentStatus!.isCompleted) {
          _resetState = ResetState.completed;
          _statusTimer?.cancel();
          _statusTimer = null;
          // 重置完成后清零错误计数
          resetSensorErrorCount();
        } else if (_currentStatus!.isFailed) {
          _resetState = ResetState.failed;
          _resetError = _currentStatus!.error ?? 'Reset failed';
          _statusTimer?.cancel();
          _statusTimer = null;
        }
        
        notifyListeners();
      } else {
        // 处理API返回错误的情况
        if (kDebugMode) print('Reset status query failed: ${response.message}');
        
        // 检查错误类型
        final errorMessage = response.message.toLowerCase();
        final isTaskNotFoundError = errorMessage.contains('404') || 
                                   errorMessage.contains('400') || 
                                   errorMessage.contains('not found') || 
                                   errorMessage.contains('task not found');
        
        // 如果曾经成功获取过状态，现在返回任务不存在错误，说明任务已完成并被清理
        if (isTaskNotFoundError && _hasEverGottenStatus && _resetState == ResetState.resetting) {
          if (kDebugMode) print('Task not found after successful queries - assuming completed');
          _resetState = ResetState.completed;
          _statusTimer?.cancel();
          _statusTimer = null;
          // 重置完成后清零错误计数
          resetSensorErrorCount();
          notifyListeners();
        }
        // 如果从未成功获取过状态且返回任务不存在错误，可能是taskId无效
        else if (isTaskNotFoundError && !_hasEverGottenStatus) {
          if (kDebugMode) print('Task not found from the beginning - invalid task ID');
          _resetState = ResetState.failed;
          _resetError = 'Invalid task ID or task was not created properly';
          _statusTimer?.cancel();
          _statusTimer = null;
          notifyListeners();
        }
      }
    } catch (e) {
      if (kDebugMode) print('Failed to check reset status: $e');
      
      // 检查是否是网络错误还是任务完成错误
      final errorMessage = e.toString().toLowerCase();
      
      // 如果是HTTP 400或404错误，且曾经成功获取过状态，认为任务已完成
      if ((errorMessage.contains('400') || errorMessage.contains('404')) && 
          _hasEverGottenStatus && _resetState == ResetState.resetting) {
        if (kDebugMode) print('HTTP error after successful queries - assuming task completed');
        _resetState = ResetState.completed;
        _statusTimer?.cancel();
        _statusTimer = null;
        // 重置完成后清零错误计数
        resetSensorErrorCount();
        notifyListeners();
      }
      // 其他错误类型暂时忽略，继续轮询
    }
  }

  /// 清除重置状态
  void clearResetState() {
    _resetState = ResetState.idle;
    _currentTaskId = null;
    _currentStatus = null;
    _resetError = null;
    _resetStartTime = null; // 清除开始时间
    _hasEverGottenStatus = false; // 重置状态获取标记
    _statusTimer?.cancel();
    _statusTimer = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _statusTimer?.cancel();
    _resetService.dispose();
    super.dispose();
  }
}
