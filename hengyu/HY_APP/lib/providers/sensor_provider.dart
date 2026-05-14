import 'dart:async';
import '../models/api_response.dart';
import 'package:flutter/foundation.dart';
import '../models/sensor_data.dart';
import '../services/api_service.dart';
import '../services/file_service.dart';
import '../services/isolate_service.dart';
import '../workers/sensor_worker.dart';
import '../providers/device_reset_provider.dart';
//------------------------------------------
import '../services/edge_upload_coordinator.dart';

class SensorProvider with ChangeNotifier {
  final ApiService _apiService = ApiService();
  final FileService _fileService = FileService();
  IsolateService? _isolateService;

  // Device reset provider reference for auto-reset functionality
  DeviceResetProvider? _deviceResetProvider;

  final Map<String, SensorData> _currentSensorData = {};
  final List<String> _availableDeviceTypes = [];

  // Historical data storage for chart display
  final Map<String, List<SensorData>> _historicalSensorData = {};
  static const int _maxHistoricalDataPoints =
      50; // Reduced from 100 to 50 for better performance

  bool _isCollecting = false;
  bool _isConnected = false;
  String _status = '未连接';
  bool _isCollectionInProgress = false;

  // Performance optimization flags
  int _updateCounter = 0;
  static const int _notificationThrottle =
      3; // Update UI every 3rd collection cycle

  String _deviceIp = '';
  int _devicePort = 502;
  int _collectionInterval = 2000; // milliseconds (every 2 seconds)

  // File saving optimization
  final List<SensorData> _pendingFileSaves = [];
  Timer? _fileSaveTimer;
  StreamSubscription? _messageSubscription;

  // Auto control polling
  Timer? _autoControlTimer;
  bool _isAutoStarted = false;
  bool _isAutoControlMode = false;
  bool _autoControlEnabled = true; // Default to true, will be updated by config

  // New Status Fields
  bool _isAlarming = false;
  int _fanSpeed = 0;

  // ---- Bridge (hy_server / 192.168.1.200) 状态 ----
  // 来自 main.py 的 GET /hy-device/sensors，由 BridgeDataManager 更新。
  double _bridgeTemperature = 0.0;
  double _bridgeLevel = 0.0;
  String _bridgeState = 'reset';
  String? _bridgeError;
  DateTime? _bridgeLastUpdateTs;
  bool _bridgeEverSeen = false; // 桥接线程是否曾经成功更新过数据
  bool _bridgeApiAvailable = false; // /hy-device/sensors 是否曾经返回过 success
  static const Duration _bridgeStaleThreshold = Duration(seconds: 10);

  // Getters
  Map<String, SensorData> get currentSensorData =>
      Map.unmodifiable(_currentSensorData);
  Map<String, List<SensorData>> get historicalSensorData =>
      Map.unmodifiable(_historicalSensorData);
  List<String> get availableDeviceTypes =>
      List.unmodifiable(_availableDeviceTypes);
  bool get isCollecting => _isCollecting;
  bool get isConnected => _isConnected;
  String get status => _status;
  bool get isAutoControlMode => _isAutoControlMode;
  String get deviceIp => _deviceIp;
  int get devicePort => _devicePort;
  int get collectionInterval => _collectionInterval;

  bool get isAlarming => _isAlarming;
  int get fanSpeed => _fanSpeed;

  // ---- Bridge getters ----
  double get bridgeTemperature => _bridgeTemperature;
  double get bridgeLevel => _bridgeLevel;
  String get bridgeState => _bridgeState;
  String? get bridgeError => _bridgeError;
  DateTime? get bridgeLastUpdateTs => _bridgeLastUpdateTs;

  /// 后端 `/hy-device/sensors` 是否成功响应过（用来决定 UI 是否显示桥接卡片）。
  /// 只要后端在线，即使桥接线程暂时未更新数据，也会显示卡片让用户感知断连。
  bool get bridgeApiAvailable => _bridgeApiAvailable;

  /// 桥接连接是否正常：必须曾经成功收到过数据、无错误、且最近一次更新不久远。
  bool get bridgeConnected {
    if (!_bridgeEverSeen) return false;
    if (_bridgeError != null && _bridgeError!.isNotEmpty) return false;
    final ts = _bridgeLastUpdateTs;
    if (ts == null) return false;
    return DateTime.now().difference(ts) <= _bridgeStaleThreshold;
  }

  // Setters
  set collectionInterval(int value) {
    _collectionInterval = value;
    if (_isCollecting) {
      _restartCollection();
    }
    notifyListeners();
  }

  /// Set device reset provider for auto-reset functionality
  void setDeviceResetProvider(DeviceResetProvider provider) {
    _deviceResetProvider = provider;
  }

  /// Set device address
  Future<bool> setDeviceAddress(String ip, int port) async {
    try {
      _status = '正在设置设备地址...';
      notifyListeners();

      final response = await _apiService.setDeviceAddress(ip, port);

      if (response.success) {
        _deviceIp = ip;
        _devicePort = port;
        _status = '设备地址已设置';
        notifyListeners();
        return true;
      } else {
        _status = '设置地址失败: ${response.message}';
        notifyListeners();
        return false;
      }
    } catch (e) {
      _status = '地址设置错误: $e';
      notifyListeners();
      return false;
    }
  }

  /// Load available device types
  Future<bool> loadDeviceTypes() async {
    try {
      _status = '正在加载设备类型...';
      notifyListeners();

      // 如果isolate服务可用，使用isolate加载设备类型
      if (_isolateService != null) {
        _isolateService!.sendMessage('sensor', {'command': 'loadDeviceTypes'});
        // 等待isolate返回设备类型，这将通过_handleIsolateMessage处理
        return true;
      } else {
        // 使用直接API调用作为fallback
        final response = await _apiService.getDeviceTypes();

        if (response.success && response.data != null) {
          _availableDeviceTypes.clear();
          // Filter out valve and light related device types - only keep sensor data
          final filteredTypes = response.data!.where((type) {
            final upperType = type.toUpperCase();
            return !upperType.contains('VALVE') &&
                !upperType.contains('LIGHT') &&
                !upperType.endsWith('_ON') &&
                !upperType.endsWith('_OFF');
          }).toList();

          _availableDeviceTypes.addAll(filteredTypes);
          _status = '设备类型已加载 (${filteredTypes.length} 个传感器)';
          notifyListeners();
          return true;
        } else {
          _status = '加载设备类型失败: ${response.message}';
          notifyListeners();
          return false;
        }
      }
    } catch (e) {
      _status = '设备类型加载错误: $e';
      notifyListeners();
      return false;
    }
  }

  /// Test device connection
  Future<bool> testConnection() async {
    try {
      _status = '正在测试连接...';
      notifyListeners();

      final response = await _apiService.testDeviceConnection();

      if (response.success && response.data == true) {
        _status = '已连接';
        notifyListeners();
        return true;
      } else {
        _status = '连接失败: ${response.message}';
        notifyListeners();
        return false;
      }
    } catch (e) {
      _status = '连接测试错误: $e';
      notifyListeners();
      return false;
    }
  }

  /// Start continuous sensor data collection (optimized)
  Future<bool> startCollection() async {
    if (_isCollecting) {
      if (kDebugMode)
        print(
            'Collection already in progress, stopping current collection first');
      stopCollection();
      await Future.delayed(const Duration(milliseconds: 300));
    }

    // 检查设备地址是否已设置
    if (_deviceIp.isEmpty) {
      _status = '采集失败: 设备IP地址未设置，请先初始化设备';
      notifyListeners();
      return false;
    }

    if (kDebugMode) print('Starting sensor data collection with isolate...');

    // Start a new file session for this collection run
    await _fileService.startNewSession();

    _isCollecting = true;
    _isConnected = true;
    _updateCounter = 0;
    _pendingFileSaves.clear();
    _status = '开始采集传感器数据...';

    try {
      // Initialize isolate service
      _isolateService = IsolateService.instance;

      // Start the isolate with basic configuration - device types will be loaded inside isolate
      await _isolateService!.startIsolate('sensor', sensorWorker, {
        'baseUrl': 'http://localhost:8000',
        'collectionInterval': _collectionInterval,
        'deviceIp': _deviceIp,
        'devicePort': _devicePort,
        'deviceTypes': [], // Start with empty list, will be loaded in isolate
      });

      // Set up message listener AFTER starting the isolate
      final messageStream = _isolateService!.getMessageStream('sensor');
      if (kDebugMode)
        print(
            '🔥 SensorProvider setting up message stream listener: ${messageStream != null}');
      _messageSubscription = messageStream?.listen(
        _handleIsolateMessage,
        onError: (Object error) {
          if (kDebugMode) print('🔥 SensorProvider stream error: $error');
        },
        onDone: () {
          if (kDebugMode) print('🔥 SensorProvider stream done');
        },
      );

      if (messageStream == null) {
        if (kDebugMode)
          print(
              '🔥 SensorProvider ERROR: Unable to get message stream for sensor');
      }

      // Wait a bit for the isolate to initialize
      await Future.delayed(Duration(milliseconds: 100));

      // First load device types in isolate
      _isolateService!.sendMessage('sensor', {
        'command': 'loadDeviceTypes',
      });

      // Wait for device types to be loaded, then start collection
      await Future.delayed(Duration(milliseconds: 500));

      // Start data collection in the isolate
      _isolateService!.sendMessage('sensor', {
        'command': 'start',
      });

      // Call backend to start monitor thread
      if (kDebugMode) print('Starting backend monitor thread...');
      await _apiService.controlMonitor('start',
          interval: _collectionInterval / 1000.0);

      //------------------------------------
      await EdgeUploadCoordinator.acquire(
          _apiService, EdgeUploadChannel.sensor);

      _status = '传感器数据采集已启动';
      notifyListeners();

      if (kDebugMode)
        print('Sensor data collection started successfully with isolate');
      return true;
    } catch (e) {
      if (kDebugMode)
        print('Failed to start sensor collection with isolate: $e');
      _status = '启动采集失败: $e';
      _isCollecting = false;
      _isConnected = false;
      notifyListeners();
      return false;
    }
  }

  /// 处理isolate消息
  void _handleIsolateMessage(Map<String, dynamic> message) {
    if (kDebugMode)
      print('🔥 SensorProvider received isolate message: $message');
    final type = message['type'];

    switch (type) {
      case 'sensor_data':
        if (kDebugMode) print('🔥 Processing sensor_data message');
        _processSensorDataFromIsolate(message);
        break;
      case 'status':
        if (kDebugMode)
          print('🔥 Processing status message: ${message['message']}');
        _status = message['message'] ?? _status;
        notifyListeners();
        break;
      case 'error':
        if (kDebugMode) print('Sensor isolate error: ${message['message']}');
        _status = '采集错误: ${message['message']}';

        // 增加错误计数，可能触发自动重置
        if (_deviceResetProvider != null) {
          _deviceResetProvider!.incrementSensorErrorCount();

          // 如果启用了自动重置且错误次数达到阈值
          if (_deviceResetProvider!.shouldAutoReset) {
            _handleAutoReset();
          }
        }

        notifyListeners();
        break;
      case 'device_types':
        if (kDebugMode)
          print(
              '🔥 Processing device_types message: ${message['deviceTypes']}');
        final deviceTypes = List<String>.from(message['deviceTypes'] ?? []);
        _availableDeviceTypes.clear();
        _availableDeviceTypes.addAll(deviceTypes);
        if (kDebugMode)
          print('🔥 Updated available device types: $_availableDeviceTypes');
        notifyListeners();
        break;
      default:
        if (kDebugMode) print('🔥 Unknown message type: $type');
        break;
    }
  }

  /// 处理来自isolate的传感器数据
  void _processSensorDataFromIsolate(Map<String, dynamic> message) {
    try {
      if (kDebugMode) print('🔥 Processing sensor data: $message');
      final data = message['data'] as Map<String, dynamic>;
      final timestamp = message['timestamp'] as String;
      final parsedTime = DateTime.parse(timestamp);

      if (kDebugMode) print('🔥 Sensor data entries: ${data.length}');

      // 更新当前传感器数据
      for (final entry in data.entries) {
        final deviceType = entry.key;
        final sensorInfo = entry.value as Map<String, dynamic>;

        final sensorData = SensorData(
          deviceType: deviceType,
          value: sensorInfo['value']?.toDouble() ?? 0.0,
          unit: sensorInfo['unit'] ?? '',
          timestamp: parsedTime,
          deviceIp: sensorInfo['deviceIp'] ?? _deviceIp,
          devicePort: sensorInfo['devicePort'] ?? _devicePort,
        );

        _currentSensorData[deviceType] = sensorData;
        _addToHistoricalDataOptimized(sensorData);
        _pendingFileSaves.add(sensorData);

        if (kDebugMode)
          print(
              '🔥 Updated sensor data for $deviceType: ${sensorData.value} ${sensorData.unit}');
      }

      // Update Fan Speed and Alarm from isolate message (if provided in metadata or as pseudo-sensors)
      // The isolate doesn't explicitly send alarm/fan in the 'data' map yet unless we modify the isolate worker.
      // But for now, we rely on polling `_checkAutoControlStatus` or manual updates.
      // However, if manual polling is active, we might want to fetch these too.

      // NOTE: The isolate currently only queries sensors. To get fan/alarm in manual mode (isolate mode),
      // we would need the isolate to also query those registers.
      // For now, we can assume `_checkAutoControlStatus` handles it if auto control is enabled.
      // If auto control is DISABLED (Manual Mode), we need another way.

      // Let's check if we are in Manual Mode and not polling auto control.
      // If so, we should poll status manually here or in a separate timer.
      if (!_autoControlEnabled) {
        // In Manual Mode, we should also fetch status occasionally.
        // We can reuse _checkAutoControlStatus() but it calls an API that reads from AutoControlManager.
        // AutoControlManager might be in "standby" but still holds state?
        // Actually, AutoControlManager thread runs even if disabled (standby).
        // So reading from it is fine.
        // We just need to ensure we poll it.
      }

      if (kDebugMode)
        print('🔥 Current sensor data count: ${_currentSensorData.length}');
      if (kDebugMode)
        print(
            '🔥 Historical data sensors: ${_historicalSensorData.keys.toList()}');

      // 立即更新UI以显示最新传感器数据
      _updateCounter++;
      if (kDebugMode)
        print('🔥 Notifying listeners immediately (update #$_updateCounter)');
      notifyListeners();

      // 保存传感器数据行 (使用新的行保存模式)
      // Pass the latest SPC path and current alarm/fan status
      _saveSensorDataRow(_currentSensorData);
    } catch (e) {
      if (kDebugMode) print('Error processing sensor data from isolate: $e');
    }
  }

  /// 安排传感器数据保存 (使用行保存模式)
  void _scheduleSensorDataSave(Map<String, SensorData> sensorDataMap) {
    // 立即保存数据行，不需要延迟
    _saveSensorDataRow(sensorDataMap);
  }

  /// Stop sensor data collection (with isolate)
  void stopCollection() {
    if (kDebugMode) print('Stopping sensor data collection with isolate...');

    _isCollecting = false;
    _isCollectionInProgress = false;

    // End the file session
    _fileService.endSession();

    // Stop isolate collection
    if (_isolateService != null) {
      _isolateService!.sendMessage('sensor', {'command': 'stop'});
      _isolateService!.stopIsolate('sensor');
      _isolateService = null;
      if (kDebugMode) print('Sensor isolate stopped');
    }

    // Stop backend monitor thread
    if (kDebugMode) print('Stopping backend monitor thread...');
    _apiService.controlMonitor('stop').catchError((e) {
      if (kDebugMode) print('Error stopping backend monitor: $e');
      return ApiResponse<Map<String, dynamic>>(
          success: false, message: e.toString());
    });

    //--------------------------------------
    unawaited(
        EdgeUploadCoordinator.release(_apiService, EdgeUploadChannel.sensor));

    // Cancel message subscription
    _messageSubscription?.cancel();
    _messageSubscription = null;

    // Cancel file save timer
    if (_fileSaveTimer != null) {
      _fileSaveTimer!.cancel();
      _fileSaveTimer = null;
      if (kDebugMode) print('File save timer cancelled');
    }

    // Save any pending data before stopping
    if (_pendingFileSaves.isNotEmpty) {
      _batchSaveToFile();
    }

    _status = _isConnected ? '已连接 - 采集已停止' : '未连接';
    notifyListeners();
    if (kDebugMode) print('Optimized sensor data collection stopped');
  }

  /// 处理自动重置
  Future<void> _handleAutoReset() async {
    if (_deviceResetProvider == null) return;

    try {
      if (kDebugMode) print('Auto reset triggered due to sensor errors');
      _status = '传感器错误累计达到阈值，正在执行自动重置...';
      notifyListeners();

      // 1. 停止所有传感器采集
      stopCollection();

      // 2. 等待确保所有worker都停止
      await Future.delayed(const Duration(seconds: 2));

      // 3. 执行重置操作
      final resetSuccess = await _deviceResetProvider!.startDeviceReset(
        customIp: _deviceIp,
      );

      if (resetSuccess) {
        _status = '设备重置已启动，等待完成...';

        // 4. 等待重置完成
        await _waitForResetCompletion();

        // 5. 重新开始传感器采集
        await Future.delayed(const Duration(seconds: 2));
        await startCollection();

        _status = '自动重置完成，传感器采集已恢复';
      } else {
        _status = '自动重置失败: ${_deviceResetProvider!.resetError}';
      }

      notifyListeners();
    } catch (e) {
      _status = '自动重置过程出错: $e';
      notifyListeners();
      if (kDebugMode) print('Auto reset error: $e');
    }
  }

  /// 等待重置完成
  Future<void> _waitForResetCompletion() async {
    if (_deviceResetProvider == null) return;

    // 最多等待60秒
    const maxWaitTime = Duration(seconds: 60);
    const pollInterval = Duration(seconds: 2);
    final startTime = DateTime.now();

    while (DateTime.now().difference(startTime) < maxWaitTime) {
      if (_deviceResetProvider!.resetState == ResetState.completed) {
        if (kDebugMode) print('Device reset completed');
        return;
      } else if (_deviceResetProvider!.resetState == ResetState.failed) {
        throw Exception('Device reset failed');
      }

      await Future.delayed(pollInterval);
    }

    throw Exception('Device reset timeout');
  }

  /// Restart collection with new interval
  void _restartCollection() async {
    if (_isCollecting) {
      print(
          'Restarting collection with new interval: ${_collectionInterval}ms');
      stopCollection();

      // Add a small delay to ensure clean shutdown
      await Future.delayed(const Duration(milliseconds: 100));

      await startCollection();
    }
  }

  /// Collect data from all available sensors
  Future<void> _collectAllSensorData() async {
    // Prevent overlapping collection operations
    if (_isCollectionInProgress) {
      print('Collection already in progress, skipping this cycle');
      return;
    }

    if (_availableDeviceTypes.isEmpty) {
      print('No device types available for data collection');
      return;
    }

    // Check if collection is still active before starting
    if (!_isCollecting) {
      print('Collection stopped, aborting sensor data collection');
      return;
    }

    _isCollectionInProgress = true;
    print('Starting sensor data collection cycle');

    final List<SensorData> newSensorData = [];
    int successCount = 0;

    try {
      // Query sensors sequentially with individual timeout and error handling
      for (final deviceType in _availableDeviceTypes) {
        // Check if collection is still active before each sensor query
        if (!_isCollecting) {
          print('Collection stopped during sensor queries, aborting');
          return;
        }

        try {
          print('Querying sensor: $deviceType');

          // Add individual timeout for each sensor query (3 seconds)
          final response = await _apiService
              .querySensorData(deviceType)
              .timeout(const Duration(seconds: 3));

          // Check again after the async operation
          if (!_isCollecting) {
            print('Collection stopped after querying $deviceType, aborting');
            return;
          }

          if (response.success && response.data != null) {
            final sensorData = SensorData(
              deviceType: deviceType,
              value: response.data!,
              unit: _getUnitForDeviceType(deviceType),
              timestamp: DateTime.now(),
              deviceIp: _deviceIp,
              devicePort: _devicePort,
            );

            _currentSensorData[deviceType] = sensorData;
            newSensorData.add(sensorData);

            // Add to historical data
            _addToHistoricalData(sensorData);

            successCount++;
            print(
                'Successfully queried $deviceType: ${response.data} ${_getUnitForDeviceType(deviceType)}');
          } else {
            print('Failed to query $deviceType: ${response.message}');
            // Create a placeholder with error status for failed sensors
            if (!_currentSensorData.containsKey(deviceType)) {
              _currentSensorData[deviceType] = SensorData(
                deviceType: deviceType,
                value: 0.0, // Default value for failed sensors
                unit: _getUnitForDeviceType(deviceType),
                timestamp: DateTime.now(),
                deviceIp: _deviceIp,
                devicePort: _devicePort,
              );
            }
          }
        } catch (e) {
          print('Error querying $deviceType: $e');
          // Check if collection is still active after error
          if (!_isCollecting) {
            print('Collection stopped during error handling, aborting');
            return;
          }
          // Create a placeholder with error status for failed sensors
          if (!_currentSensorData.containsKey(deviceType)) {
            _currentSensorData[deviceType] = SensorData(
              deviceType: deviceType,
              value: 0.0, // Default value for error sensors
              unit: _getUnitForDeviceType(deviceType),
              timestamp: DateTime.now(),
              deviceIp: _deviceIp,
              devicePort: _devicePort,
            );
          }
        }

        // Check if collection is still active before delay
        if (!_isCollecting) {
          print('Collection stopped before delay, aborting');
          return;
        }

        // Add a small delay between sensor queries to avoid overwhelming the device
        await Future.delayed(const Duration(milliseconds: 200));
      }

      // Final check before updating status and saving data
      if (!_isCollecting) {
        print('Collection stopped before final updates, aborting');
        return;
      }

      // Update status based on collection results
      if (successCount > 0) {
        _status =
            '正在采集数据... ($successCount/${_availableDeviceTypes.length} 个传感器活跃)';
      } else {
        _status = '采集失败 - 未接收到数据';
      }

      // Save one unified row only if we have successful readings
      if (successCount > 0 && _currentSensorData.isNotEmpty) {
        await _saveSensorDataRow(_currentSensorData);
        print('保存了一行传感器数据 (${successCount} 个传感器)');
      }

      // Always notify listeners to update UI, even with placeholders
      notifyListeners();
    } finally {
      _isCollectionInProgress = false;
      print('Sensor data collection cycle completed');
    }
  }

  /// Optimized sensor data collection with batching and throttling
  Future<void> _collectAllSensorDataOptimized() async {
    // Prevent overlapping collection operations
    if (_isCollectionInProgress) {
      if (kDebugMode)
        print('Collection already in progress, skipping this cycle');
      return;
    }

    if (_availableDeviceTypes.isEmpty) {
      if (kDebugMode) print('No device types available for data collection');
      return;
    }

    // Check if collection is still active before starting
    if (!_isCollecting) {
      if (kDebugMode)
        print('Collection stopped, aborting sensor data collection');
      return;
    }

    _isCollectionInProgress = true;
    if (kDebugMode) print('Starting optimized sensor data collection cycle');

    final List<SensorData> newSensorData = [];
    int successCount = 0;

    try {
      // Query sensors sequentially with optimized error handling
      for (final deviceType in _availableDeviceTypes) {
        // Check if collection is still active before each sensor query
        if (!_isCollecting) {
          if (kDebugMode)
            print('Collection stopped during sensor queries, aborting');
          return;
        }

        try {
          // Reduced timeout for faster response (2 seconds instead of 3)
          final response = await _apiService
              .querySensorData(deviceType)
              .timeout(const Duration(seconds: 2));

          // Check again after the async operation
          if (!_isCollecting) {
            if (kDebugMode)
              print('Collection stopped after querying $deviceType, aborting');
            return;
          }

          if (response.success && response.data != null) {
            final sensorData = SensorData(
              deviceType: deviceType,
              value: response.data!,
              unit: _getUnitForDeviceType(deviceType),
              timestamp: DateTime.now(),
              deviceIp: _deviceIp,
              devicePort: _devicePort,
            );

            _currentSensorData[deviceType] = sensorData;
            newSensorData.add(sensorData);

            // Add to historical data with optimization
            _addToHistoricalDataOptimized(sensorData);

            successCount++;
            if (kDebugMode)
              print(
                  'Successfully queried $deviceType: ${response.data} ${_getUnitForDeviceType(deviceType)}');
          } else {
            if (kDebugMode)
              print('Failed to query $deviceType: ${response.message}');
            // Create a placeholder with error status for failed sensors
            if (!_currentSensorData.containsKey(deviceType)) {
              _currentSensorData[deviceType] = SensorData(
                deviceType: deviceType,
                value: 0.0,
                unit: _getUnitForDeviceType(deviceType),
                timestamp: DateTime.now(),
                deviceIp: _deviceIp,
                devicePort: _devicePort,
              );
            }
          }
        } catch (e) {
          if (kDebugMode) print('Error querying $deviceType: $e');
          // Check if collection is still active after error
          if (!_isCollecting) {
            if (kDebugMode)
              print('Collection stopped during error handling, aborting');
            return;
          }
          // Create a placeholder with error status for failed sensors
          if (!_currentSensorData.containsKey(deviceType)) {
            _currentSensorData[deviceType] = SensorData(
              deviceType: deviceType,
              value: 0.0,
              unit: _getUnitForDeviceType(deviceType),
              timestamp: DateTime.now(),
              deviceIp: _deviceIp,
              devicePort: _devicePort,
            );
          }
        }

        // Check if collection is still active before delay
        if (!_isCollecting) {
          if (kDebugMode) print('Collection stopped before delay, aborting');
          return;
        }

        // Reduced delay between sensor queries (100ms instead of 200ms)
        await Future.delayed(const Duration(milliseconds: 100));
      }

      // Final check before updating status and saving data
      if (!_isCollecting) {
        if (kDebugMode)
          print('Collection stopped before final updates, aborting');
        return;
      }

      // Update status based on collection results
      if (successCount > 0) {
        _status =
            '正在采集数据... ($successCount/${_availableDeviceTypes.length} 个传感器活跃)';
      } else {
        _status = '采集失败 - 未接收到数据';
      }

      // Save one unified row only if we have data from all available sensors
      if (successCount > 0 && _currentSensorData.isNotEmpty) {
        await _saveSensorDataRow(_currentSensorData);
        if (kDebugMode) print('保存了一行传感器数据 (${successCount} 个传感器)');
      }

      // Throttled UI updates - only notify every few cycles
      _updateCounter++;
      if (_updateCounter >= _notificationThrottle) {
        notifyListeners();
        _updateCounter = 0;
      }
    } finally {
      _isCollectionInProgress = false;
      if (kDebugMode) print('Optimized sensor data collection cycle completed');
    }
  }

  /// Get unit for device type
  String _getUnitForDeviceType(String deviceType) {
    switch (deviceType.toUpperCase()) {
      case 'PH':
        return 'pH';
      case 'PH_TEMP':
      case 'TEMP':
      case 'PT100':
        return '°C';
      case 'DDL':
        return 'μS/cm';
      default:
        return '';
    }
  }

  /// Optimized historical data management with size limits
  void _addToHistoricalDataOptimized(SensorData sensorData) {
    if (!_historicalSensorData.containsKey(sensorData.deviceType)) {
      _historicalSensorData[sensorData.deviceType] = [];
    }

    _historicalSensorData[sensorData.deviceType]!.add(sensorData);

    // Keep only the last 50 data points per sensor (reduced from 100)
    if (_historicalSensorData[sensorData.deviceType]!.length > 50) {
      _historicalSensorData[sensorData.deviceType]!.removeAt(0);
    }
  }

  /// Save sensor data to file using unified CSV format
  Future<void> _saveSensorData(List<SensorData> sensorDataList) async {
    try {
      await _fileService.saveSensorDataUnified(sensorDataList);
    } catch (e) {
      print('Error saving sensor data: $e');
    }
  }

  /// Save sensor data row to file using new unified format (one row per collection cycle)
  Future<void> _saveSensorDataRow(Map<String, SensorData> sensorDataMap) async {
    try {
      await _fileService.saveSensorDataRow(
          sensorDataMap,
          null,
          FileService.latestSpcPath,
          _isAlarming,
          _fanSpeed,
          _bridgeEverSeen ? _bridgeTemperature : null,
          _bridgeEverSeen ? _bridgeLevel : null);
    } catch (e) {
      if (kDebugMode) print('Error saving sensor data row: $e');
    }
  }

  /// Batch save sensor data to reduce file I/O operations (DEPRECATED - using row-based saving now)
  Future<void> _batchSaveToFile() async {
    // This method is deprecated since we now save one row per collection cycle
    // Clear any pending saves to free memory
    _pendingFileSaves.clear();
    if (kDebugMode) print('已清理待保存的传感器数据 (现在使用行保存模式)');
  }

  /// Manually collect data from all sensors
  Future<bool> collectSingleReading() async {
    try {
      _status = 'Collecting single reading...';
      notifyListeners();

      // Ensure device types are loaded
      if (_availableDeviceTypes.isEmpty) {
        bool typesLoaded = await loadDeviceTypes();
        if (!typesLoaded) {
          _status = 'Failed to load device types for single reading';
          notifyListeners();
          return false;
        }
      }

      await _collectAllSensorData();

      _status = _isCollecting ? '采集传感器数据中...' : '单次读取已完成';
      notifyListeners();
      return true;
    } catch (e) {
      _status = '采集错误: $e';
      notifyListeners();
      return false;
    }
  }

  /// Query specific sensor data
  Future<bool> querySingleSensor(String deviceType) async {
    if (!_isConnected) {
      _status = 'Device not connected';
      notifyListeners();
      return false;
    }

    try {
      final response = await _apiService.querySensorData(deviceType);

      if (response.success && response.data != null) {
        final sensorData = SensorData(
          deviceType: deviceType,
          value: response.data!,
          unit: _getUnitForDeviceType(deviceType),
          timestamp: DateTime.now(),
          deviceIp: _deviceIp,
          devicePort: _devicePort,
        );

        _currentSensorData[deviceType] = sensorData;

        // Save single sensor data
        await _fileService.appendSensorData(sensorData);

        notifyListeners();
        return true;
      } else {
        print('Failed to query $deviceType: ${response.message}');
        return false;
      }
    } catch (e) {
      print('Error querying $deviceType: $e');
      return false;
    }
  }

  /// Initialize sensors (set address, load types, test connection)
  Future<bool> initializeSensors(String ip, int port) async {
    try {
      _status = 'Initializing sensors...';
      notifyListeners();

      _startAutoControlPolling(); // Start polling for auto control

      // Set device address first
      bool addressSet = await setDeviceAddress(ip, port);
      if (!addressSet) {
        _status = 'Failed to set device address';
        notifyListeners();
        return false;
      }

      // Load initial auto control config
      await _loadAutoControlConfig();

      // Wait a moment for the address to be set
      await Future.delayed(const Duration(milliseconds: 500));

      // Load device types
      bool typesLoaded = await loadDeviceTypes();
      if (!typesLoaded) {
        _status = 'Failed to load device types';
        notifyListeners();
        return false;
      }

      // Test connection
      bool connected = await testConnection();
      if (!connected) {
        _status = 'Connection test failed, but continuing initialization';
        // Don't return false here, as we may still be able to collect data
        _isConnected = true; // Set as connected for demo purposes
      }

      _status = 'Sensors initialized successfully';
      notifyListeners();
      return true;
    } catch (e) {
      _status = 'Initialization error: $e';
      notifyListeners();
      return false;
    }
  }

  Future<void> _loadAutoControlConfig() async {
    try {
      final response = await _apiService.getDeviceSettings();
      if (response.success && response.data != null) {
        final enabled = response.data!.autoControl.enabled;
        setAutoControlEnabled(enabled);
      }
    } catch (e) {
      if (kDebugMode) print('Error loading auto control config: $e');
    }
  }

  /// Set auto control enabled status
  void setAutoControlEnabled(bool enabled) {
    if (_autoControlEnabled != enabled) {
      _autoControlEnabled = enabled;
      if (enabled) {
        _startAutoControlPolling();
      } else {
        _stopAutoControlPolling();
        // Force exit auto control mode immediately
        if (_isAutoControlMode) {
          _isAutoControlMode = false;
          notifyListeners();
        }
      }
    }
  }

  // Poll auto control status (or manual status monitoring)
  void _startAutoControlPolling() {
    _autoControlTimer?.cancel();
    // Always start polling to get status updates (fan speed, alarm, auto mode state)
    // This is needed even in Manual Mode to show Fan Speed and Alarm status.

    _autoControlTimer =
        Timer.periodic(Duration(milliseconds: 1000), (timer) async {
      await _checkAutoControlStatus();
    });
  }

  void _stopAutoControlPolling() {
    // We might NOT want to stop polling if we want to keep seeing Fan Speed in manual mode.
    // But if we want to save resources when "disconnected", we can stop.
    _autoControlTimer?.cancel();
    _autoControlTimer = null;
  }

  /// 拉取 /hy-device/sensors 中由 hy_server.BridgeDataManager 提供的字段
  /// （temperature / level / bridge_state / bridge_error / bridge_last_update_ts），
  /// 用于驱动状态指示灯与额外的"桥接温度 / 液位"传感器卡片。
  Future<void> _refreshBridgeSnapshot() async {
    try {
      final resp = await _apiService.getSensorsSnapshot();
      if (!resp.success || resp.data == null) {
        // 首次失败不当作"已连接"，无需触发额外通知。
        if (_bridgeEverSeen) {
          // 标记一次失败：清除 last_update_ts 让 bridgeConnected 走超时分支。
          notifyListeners();
        }
        return;
      }
      final data = resp.data!;

      double parseDouble(dynamic v) {
        if (v == null) return 0.0;
        if (v is num) return v.toDouble();
        return double.tryParse(v.toString()) ?? 0.0;
      }

      DateTime? parseTs(dynamic v) {
        if (v == null) return null;
        if (v is num) {
          return DateTime.fromMillisecondsSinceEpoch(
            (v.toDouble() * 1000).round(),
          );
        }
        return null;
      }

      final newTemp = parseDouble(data['temperature']);
      final newLevel = parseDouble(data['level']);
      final newState = (data['bridge_state'] as String?) ?? _bridgeState;
      final newErr = data['bridge_error'] as String?;
      final newTs = parseTs(data['bridge_last_update_ts']);

      final changed = newTemp != _bridgeTemperature ||
          newLevel != _bridgeLevel ||
          newState != _bridgeState ||
          newErr != _bridgeError ||
          newTs != _bridgeLastUpdateTs ||
          !_bridgeApiAvailable;

      _bridgeTemperature = newTemp;
      _bridgeLevel = newLevel;
      _bridgeState = newState;
      _bridgeError = newErr;
      _bridgeLastUpdateTs = newTs;
      if (newTs != null) {
        _bridgeEverSeen = true;
      }
      _bridgeApiAvailable = true;

      if (changed) notifyListeners();
    } catch (e) {
      if (kDebugMode) print('Bridge snapshot fetch error: $e');
    }
  }

  Future<void> _checkAutoControlStatus() async {
    // 顺带拉取桥接状态（hy_server.BridgeDataManager），驱动连接指示灯与额外卡片。
    unawaited(_refreshBridgeSnapshot());
    try {
      final response = await _apiService.getAutoControlStatus();
      if (response.success && response.data != null) {
        final status = response.data!;
        // Handle potential boolean or integer types for 'running'
        bool isRunning = false;
        if (status['running'] is bool) {
          isRunning = status['running'];
        } else if (status['running'] is int) {
          isRunning = (status['running'] as int) != 0;
        }

        final isActionActive = status['is_action_active'] as bool? ?? false;

        // Parse alarm and fan status
        bool newAlarming = status['is_alarming'] as bool? ?? false;
        int newFanSpeed = status['fan_speed'] as int? ?? 0;

        if (_isAlarming != newAlarming || _fanSpeed != newFanSpeed) {
          _isAlarming = newAlarming;
          _fanSpeed = newFanSpeed;
          notifyListeners();
        }

        // Update auto control mode status
        if (_isAutoControlMode != isRunning) {
          if (kDebugMode)
            print(
                '🔍 SensorProvider: Switching Auto Control Mode to $isRunning');
          _isAutoControlMode = isRunning;
          notifyListeners();
        }

        if (isActionActive && !_isCollecting && !_isAutoStarted) {
          if (kDebugMode)
            print(
                'Auto-starting sensor collection due to backend action active.');
          // Ensure initialized/connected? Maybe just try start.
          // Initialize if needed?
          if (!_isConnected) {
            // Try to initialize with stored IP/Port?
            // Or assume already initialized.
            await testConnection();
          }

          await startCollection();
          _isAutoStarted = true;
        } else if (!isActionActive && (_isCollecting || _isAutoStarted)) {
          if (_isAutoStarted) {
            if (kDebugMode)
              print(
                  'Auto-stopping sensor collection due to backend action inactive.');
            stopCollection();
            _isAutoStarted = false;
          }
        }
      }
    } catch (e) {
      // silent error
    }
  }

  /// Disconnect sensors
  void disconnect() {
    print('Disconnecting sensors...');

    // Stop any ongoing collection
    stopCollection();

    // Clear all state
    _isConnected = false;
    _currentSensorData.clear();
    _availableDeviceTypes.clear();
    _status = 'Disconnected';

    print('Sensors disconnected and all data cleared');
    notifyListeners();
  }

  /// Add sensor data to historical data storage
  void _addToHistoricalData(SensorData sensorData) {
    final deviceType = sensorData.deviceType;

    // Initialize list if it doesn't exist
    if (!_historicalSensorData.containsKey(deviceType)) {
      _historicalSensorData[deviceType] = [];
    }

    // Add new data point
    _historicalSensorData[deviceType]!.add(sensorData);

    // Keep only the last _maxHistoricalDataPoints data points
    if (_historicalSensorData[deviceType]!.length > _maxHistoricalDataPoints) {
      _historicalSensorData[deviceType]!.removeAt(0);
    }
  }

  /// Clear historical data for all sensors
  void clearHistoricalData() {
    _historicalSensorData.clear();
    notifyListeners();
  }

  /// Clear historical data for a specific sensor
  void clearHistoricalDataForSensor(String deviceType) {
    _historicalSensorData.remove(deviceType);
    notifyListeners();
  }

  @override
  void dispose() {
    if (kDebugMode) print('Disposing SensorProvider...');

    // Stop collection and clean up isolate
    if (_isolateService != null) {
      _isolateService!.sendMessage('sensor', {'command': 'stop'});
      _isolateService!.stopIsolate('sensor');
      _isolateService = null;
    }

    // Cancel message subscription
    _messageSubscription?.cancel();
    _messageSubscription = null;

    if (_fileSaveTimer != null) {
      _fileSaveTimer!.cancel();
      _fileSaveTimer = null;
    }

    // Save any pending data before disposing
    if (_pendingFileSaves.isNotEmpty) {
      _batchSaveToFile();
    }

    // Clear all data
    _currentSensorData.clear();
    _availableDeviceTypes.clear();
    _historicalSensorData.clear();
    _pendingFileSaves.clear();

    // Dispose API service
    _apiService.dispose();

    if (kDebugMode) print('SensorProvider disposed');
    super.dispose();
  }
}
