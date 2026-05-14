import 'dart:async';
import 'package:flutter/foundation.dart';
import '../models/spectrum_data.dart';
import '../models/device_config.dart';
import '../services/api_service.dart';
import '../services/file_service.dart';
import '../services/settings_service.dart';
import '../services/isolate_service.dart';
import '../workers/spectrum_worker.dart';
import '../providers/device_reset_provider.dart';
//------------------------------------------
import '../services/edge_upload_coordinator.dart';

class SpectrumProvider with ChangeNotifier {
  final ApiService _apiService = ApiService();
  final FileService _fileService = FileService();
  final SettingsService _settingsService = SettingsService();
  IsolateService? _isolateService;
  StreamSubscription? _messageSubscription;

  // Device reset provider reference for auto-reset functionality
  DeviceResetProvider? _deviceResetProvider;

  SpectrumData? _currentSpectrum;
  bool _isCollecting = false;
  bool _isInitialized = false;
  String _status = '未连接';
  
  // Configuration
  int _integrationTime = 10000; // microseconds
  int _scansToAverage = 3;
  int _collectionInterval = 1000; // milliseconds
  
  // Auto control polling
  Timer? _autoControlTimer;
  bool _isAutoStarted = false;
  bool _isAutoControlMode = false;
  bool _autoControlEnabled = true; // Default to true, will be updated by config

  // Initialize and load user settings
  Future<void> initialize() async {
    await _loadUserSettings();
    await _loadAutoControlConfig();
    
    // Ensure polling is started if enabled (setAutoControlEnabled might skip if value is same)
    if (_autoControlEnabled) {
      _startAutoControlPolling();
    }
    
    notifyListeners();
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
  
  // Poll auto control status
  void _startAutoControlPolling() {
    _autoControlTimer?.cancel();
    if (!_autoControlEnabled) return; // Don't start if disabled

    _autoControlTimer = Timer.periodic(Duration(milliseconds: 1000), (timer) async {
      await _checkAutoControlStatus();
    });
  }

  void _stopAutoControlPolling() {
    _autoControlTimer?.cancel();
    _autoControlTimer = null;
  }
  
  Future<void> _checkAutoControlStatus() async {
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
        
        // print('🔍 SpectrumProvider: running=$isRunning, action=$isActionActive, currentMode=$_isAutoControlMode');

        // Update auto control mode status
        if (_isAutoControlMode != isRunning) {
          print('🔍 SpectrumProvider: Switching Auto Control Mode to $isRunning');
          _isAutoControlMode = isRunning;
          notifyListeners();
        }
        
        // Update: use isActionActive instead of just signalVal=1
        if (isActionActive && !_isCollecting && !_isAutoStarted) {
             // Poll spectrum status from backend
             try {
               // We need to make sure we initialize the device first if not initialized.
               if (!_isInitialized) {
                  await initializeDevice();
               }
               
               if (_isInitialized) {
                  print('Auto-starting frontend spectrum collection due to backend action active.');
                  await startCollection();
                  _isAutoStarted = true; 
               }
             } catch (e) {
               print('Error auto-starting collection: $e');
             }
        } else if (!isActionActive && (_isCollecting || _isAutoStarted)) {
             if (_isAutoStarted) {
                 print('Auto-stopping frontend spectrum collection due to backend action inactive.');
                 stopCollection();
                 _isAutoStarted = false;
             }
        }
      }
    } catch (e) {
      // silent error
    }
  }

  // Load user settings from storage
  Future<void> _loadUserSettings() async {
    _integrationTime = await _settingsService.getIntegrationTime();
    _scansToAverage = await _settingsService.getScansToAverage();
    final queryIntervalSeconds = await _settingsService.getSpectrumQueryInterval();
    _collectionInterval = queryIntervalSeconds * 1000; // Convert to milliseconds
    await _apiService.updateSpectrumQueryInterval(queryIntervalSeconds);
  }

  Future<SpectrumFileFormat> _getSpectrumSaveFormat() async {
    return await _settingsService.getSpectrumFileFormat();
  }

  // Save current settings to storage
  Future<void> saveSettings() async {
    await _settingsService.setIntegrationTime(_integrationTime);
    await _settingsService.setScansToAverage(_scansToAverage);
    await _settingsService.setSpectrumQueryInterval(_collectionInterval ~/ 1000); // Convert to seconds
  }

  // Getters
  SpectrumData? get currentSpectrum => _currentSpectrum;
  bool get isCollecting => _isCollecting;
  bool get isInitialized => _isInitialized;
  String get status => _status;
  bool get isAutoControlMode => _isAutoControlMode;
  int get integrationTime => _integrationTime;
  int get scansToAverage => _scansToAverage;
  int get collectionInterval => _collectionInterval;
  int get queryIntervalSeconds => _collectionInterval ~/ 1000;

  /// 更新当前光谱数据（用于在线分析）
  void updateCurrentSpectrum(SpectrumData spectrumData) {
    _currentSpectrum = spectrumData;
    notifyListeners();
  }

  // Setters with settings persistence
  set integrationTime(int value) {
    _integrationTime = value;
    saveSettings();
    notifyListeners();
  }

  set scansToAverage(int value) {
    _scansToAverage = value;
    saveSettings();
    notifyListeners();
  }

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

  /// Initialize CDS350 device
  Future<bool> initializeDevice() async {
    try {
      _status = '正在初始化...';
      notifyListeners();

      final response = await _apiService.initializeCDS350();
      
      if (response.success) {
        _isInitialized = true;
        _status = '已初始化';
        
        // Configure device with current settings
        await _configureDevice();
        
        notifyListeners();
        return true;
      } else {
        _status = '初始化失败: ${response.message}';
        _isInitialized = false;
        notifyListeners();
        return false;
      }
    } catch (e) {
      _status = '初始化错误: $e';
      _isInitialized = false;
      notifyListeners();
      return false;
    }
  }

  /// Configure device with current settings
  Future<bool> _configureDevice() async {
    try {
      final config = CDS350Config(
        integrationTime: _integrationTime,
        scansToAverage: _scansToAverage,
      );

      final response = await _apiService.configureCDS350(config);
      return response.success;
    } catch (e) {
      print('Configuration error: $e');
      return false;
    }
  }

  /// Start continuous spectrum collection
  Future<bool> startCollection() async {
    if (!_isInitialized) {
      _status = '设备未初始化';
      notifyListeners();
      return false;
    }

    if (_isCollecting) {
      return true; // Already collecting
    }

    _isCollecting = true;
    _status = '正在采集...';
    notifyListeners();

    try {
      // Initialize isolate service
      _isolateService = IsolateService.instance;
      
      // Set up message listener AFTER the isolate is started
      final started = await _isolateService!.startIsolate('spectrum', spectrumWorker, {
        'baseUrl': 'http://localhost:8000',
        'collectionInterval': _collectionInterval,
        'integrationTime': _integrationTime,
        'scansToAverage': _scansToAverage,
      });
      
      if (!started) {
        throw Exception('Failed to start spectrum isolate');
      }
      
      // Wait a bit for the isolate to initialize
      await Future.delayed(Duration(milliseconds: 100));
      
      // Set up message listener
      final messageStream = _isolateService!.getMessageStream('spectrum');
      if (kDebugMode) print('🔥 SpectrumProvider setting up message stream listener: ${messageStream != null}');
      if (messageStream != null) {
        _messageSubscription = messageStream.listen(
          _handleIsolateMessage,
          onError: (error) {
            if (kDebugMode) print('🔥 SpectrumProvider stream error: $error');
          },
          onDone: () {
            if (kDebugMode) print('🔥 SpectrumProvider stream done');
          },
        );
        if (kDebugMode) print('🔥 SpectrumProvider message listener set up successfully');
      } else {
        if (kDebugMode) print('🔥 SpectrumProvider failed to get message stream');
      }
      
      // Start data collection in the isolate
      _isolateService!.sendMessage('spectrum', {
        'command': 'start',
      });
      
      //------------------------------------
      await EdgeUploadCoordinator.acquire(_apiService, EdgeUploadChannel.spc);
      _status = '光谱采集已启动';
      notifyListeners();
      
      return true;
    } catch (e) {
      if (kDebugMode) print('Failed to start spectrum collection with isolate: $e');
      _status = '启动采集失败: $e';
      _isCollecting = false;
      notifyListeners();
      return false;
    }
  }

  /// 处理isolate消息
  void _handleIsolateMessage(Map<String, dynamic> message) {
    if (kDebugMode) print('🔥 SpectrumProvider received isolate message: ${message.keys}');
    final type = message['type'];
    
    switch (type) {
      case 'spectrum_data':
        final wavelengths = message['wavelengths'] as List?;
        final intensities = message['intensities'] as List?;
        if (kDebugMode) print('🔥 Processing spectrum_data message: ${wavelengths?.length ?? 0} wavelengths, ${intensities?.length ?? 0} intensities');
        _processSpectrumDataFromIsolate(message);
        break;
      case 'status':
        if (kDebugMode) print('🔥 Processing status message: ${message['message']}');
        _status = message['message'] ?? _status;
        notifyListeners();
        break;
      case 'error':
        if (kDebugMode) print('Spectrum isolate error: ${message['message']}');
        _status = '采集错误: ${message['message']}';
        
        // 检查是否为光谱采集错误，如果是则增加错误计数
        if (message['error_type'] == 'spectrum_error' && _deviceResetProvider != null) {
          _deviceResetProvider!.incrementSensorErrorCount();
          
          // 如果启用了自动重置且错误次数达到阈值
          if (_deviceResetProvider!.shouldAutoReset) {
            _handleAutoReset();
          }
        }
        
        notifyListeners();
        break;
      default:
        if (kDebugMode) print('🔥 Unknown spectrum message type: $type');
        break;
    }
  }

  /// 处理来自isolate的光谱数据
  void _processSpectrumDataFromIsolate(Map<String, dynamic> message) async {
    try {
      print('🔥 Processing spectrum data: ${message['wavelengths']?.length ?? 0} wavelengths, ${message['intensities']?.length ?? 0} intensities');
      final wavelengths = List<double>.from(message['wavelengths'] ?? []);
      final intensities = List<double>.from(message['intensities'] ?? []);
      final timestamp = message['timestamp'] as String?;
      final lastAcquisitionTime = message['lastAcquisitionTime'] as double?;
      final acquisitionStatus = message['acquisitionStatus'] as Map<String, dynamic>?;
      
      if (wavelengths.isNotEmpty && intensities.isNotEmpty) {
        print('🔥 Creating spectrum data with ${wavelengths.length} points');
        _currentSpectrum = SpectrumData(
          wavelengths: wavelengths,
          intensities: intensities.map((e) => e.toInt()).toList(),
          timestamp: timestamp != null ? DateTime.parse(timestamp) : DateTime.now(),
          length: wavelengths.length,
          integrationTime: _integrationTime,
          scansToAverage: _scansToAverage,
          lastAcquisitionTime: lastAcquisitionTime,
          acquisitionStatus: acquisitionStatus,
        );
        
        // Save to file using frontend timestamp
        print('🔥 Saving spectrum data to file');
        try {
          final saveFormat = await _getSpectrumSaveFormat();
          final saveSuccess = await _fileService.saveSpectrumData(
            _currentSpectrum!,
            null,
            saveFormat,
          );
          if (saveSuccess) {
            print('🔥 Spectrum data saved successfully');
          } else {
            print('🔥 Failed to save spectrum data');
          }
        } catch (e) {
          print('🔥 Error saving spectrum data: $e');
        }
        
        print('🔥 Notifying spectrum listeners');
        notifyListeners();
      } else {
        print('🔥 Empty spectrum data received');
      }
    } catch (e) {
      if (kDebugMode) print('Error processing spectrum data from isolate: $e');
    }
  }

  /// Stop spectrum collection
  void stopCollection() {
    if (_isolateService != null) {
      _isolateService!.sendMessage('spectrum', {'command': 'stop'});
      _isolateService!.stopIsolate('spectrum');
      _isolateService = null;
    }
    
    _messageSubscription?.cancel();
    _messageSubscription = null;
    
    _isCollecting = false;
    _status = '采集已停止';
    notifyListeners();
    
    //--------------------------------------
    unawaited(EdgeUploadCoordinator.release(_apiService, EdgeUploadChannel.spc));
  }

  /// Restart collection (used when settings change)
  void _restartCollection() async {
    if (_isCollecting) {
      stopCollection();
      await Future.delayed(Duration(milliseconds: 500));
      await startCollection();
    }
  }

  /// Handle auto reset
  void _handleAutoReset() async {
    print('Auto reset triggered');
    stopCollection();
    
    // Wait for a moment before reinitializing
    await Future.delayed(Duration(seconds: 2));
    
    final initialized = await initializeDevice();
    if (initialized) {
      await startCollection();
    }
  }

  /// Manually reset device
  Future<bool> resetDevice() async {
    stopCollection();
    
    _isInitialized = false;
    _status = '正在重置...';
    notifyListeners();
    
    try {
      // Use the existing initialization endpoint for reset
      final response = await _apiService.initializeCDS350();
      if (response.success) {
        _status = '重置成功';
        notifyListeners();
        return await initializeDevice();
      } else {
        _status = '重置失败: ${response.message}';
        notifyListeners();
        return false;
      }
    } catch (e) {
      _status = '重置错误: $e';
      notifyListeners();
      return false;
    }
  }

  /// Capture single spectrum
  Future<bool> captureSpectrum() async {
    if (!_isInitialized) {
      _status = '设备未初始化';
      notifyListeners();
      return false;
    }

    try {
      _status = '正在采集光谱...';
      notifyListeners();

      // Use the existing getSpectrumData method with current zjType
      final response = await _apiService.getSpectrumData();
      
      if (response.success && response.data != null) {
        _currentSpectrum = response.data!;
        
        print('🔍 [Provider Debug] Received spectrum data:');
        print('  - lastAcquisitionTime: ${_currentSpectrum!.lastAcquisitionTime}');
        
        // Save to file
        final saveFormat = await _getSpectrumSaveFormat();
        await _fileService.saveSpectrumData(_currentSpectrum!, null, saveFormat);
        
        _status = '光谱采集成功';
        notifyListeners();
        return true;
      } else {
        _status = '采集失败: ${response.message}';
        notifyListeners();
        return false;
      }
    } catch (e) {
      _status = '采集错误: $e';
      notifyListeners();
      return false;
    }
  }

  /// Close device connection (alias for stopCollection)
  Future<bool> closeDevice() async {
    stopCollection();
    _isInitialized = false;
    _status = '未连接';
    notifyListeners();
    return true;
  }

  /// Collect single spectrum (alias for captureSpectrum)
  Future<bool> collectSingleSpectrum() async {
    return await captureSpectrum();
  }

  @override
  void dispose() {
    stopCollection();
    super.dispose();
  }
}
