import 'dart:async';
import 'package:flutter/foundation.dart';
import '../models/spectrum_data.dart';
import '../models/dye_content_data.dart';
import '../models/additive_content_data.dart';
import '../models/device_config.dart';
import '../services/api_service.dart';
import '../services/file_service.dart';
import '../services/settings_service.dart';
import '../services/isolate_service.dart';
import '../workers/spectrum_worker.dart';
import '../providers/device_reset_provider.dart';

class SpectrumProvider with ChangeNotifier {
  final ApiService _apiService = ApiService();
  final FileService _fileService = FileService();
  final SettingsService _settingsService = SettingsService();
  IsolateService? _isolateService;
  StreamSubscription? _messageSubscription;

  // Device reset provider reference for auto-reset functionality
  DeviceResetProvider? _deviceResetProvider;

  SpectrumData? _currentSpectrum;
  DyeContentData? _currentDyeContent;
  AdditiveContentData? _currentAdditiveContent;
  List<DyeContentData> _historicalDyeContentData = []; // 历史染料含量数据
  List<AdditiveContentData> _historicalAdditiveContentData = []; // 历史助剂含量数据
  double? _lastSavedAcquisitionTime; // 记录上次保存的acquisition_time
  String _currentZjType = 'A型'; // 当前助剂类型
  bool _isCollecting = false;
  bool _isInitialized = false;
  String _status = 'Disconnected';
  
  // Configuration
  int _integrationTime = 10000; // microseconds
  int _scansToAverage = 3;
  int _collectionInterval = 1000; // milliseconds

  // Initialize and load user settings
  Future<void> initialize() async {
    await _loadUserSettings();
    notifyListeners();
  }

  // Load user settings from storage
  Future<void> _loadUserSettings() async {
    _integrationTime = await _settingsService.getIntegrationTime();
    _scansToAverage = await _settingsService.getScansToAverage();
    final queryIntervalSeconds = await _settingsService.getSpectrumQueryInterval();
    _collectionInterval = queryIntervalSeconds * 1000; // Convert to milliseconds
  }

  // Save current settings to storage
  Future<void> saveSettings() async {
    await _settingsService.setIntegrationTime(_integrationTime);
    await _settingsService.setScansToAverage(_scansToAverage);
    await _settingsService.setSpectrumQueryInterval(_collectionInterval ~/ 1000); // Convert to seconds
  }

  // Getters
  SpectrumData? get currentSpectrum => _currentSpectrum;
  DyeContentData? get currentDyeContent => _currentDyeContent;
  AdditiveContentData? get currentAdditiveContent => _currentAdditiveContent;
  List<DyeContentData> get historicalDyeContentData => _historicalDyeContentData;
  List<AdditiveContentData> get historicalAdditiveContentData => _historicalAdditiveContentData;
  String get currentZjType => _currentZjType;
  bool get isCollecting => _isCollecting;
  bool get isInitialized => _isInitialized;
  String get status => _status;
  int get integrationTime => _integrationTime;
  int get scansToAverage => _scansToAverage;
  int get collectionInterval => _collectionInterval;
  int get queryIntervalSeconds => _collectionInterval ~/ 1000;

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

  /// Set zj_type (助剂类型)
  set zjType(String value) {
    _currentZjType = value;
    notifyListeners();
  }

  /// Set device reset provider for auto-reset functionality
  void setDeviceResetProvider(DeviceResetProvider provider) {
    _deviceResetProvider = provider;
  }

  /// Initialize CDS350 device
  Future<bool> initializeDevice() async {
    try {
      _status = 'Initializing...';
      notifyListeners();

      final response = await _apiService.initializeCDS350();
      
      if (response.success) {
        _isInitialized = true;
        _status = 'Initialized';
        
        // Configure device with current settings
        await _configureDevice();
        
        notifyListeners();
        return true;
      } else {
        _status = 'Initialization failed: ${response.message}';
        _isInitialized = false;
        notifyListeners();
        return false;
      }
    } catch (e) {
      _status = 'Initialization error: $e';
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
      _status = 'Device not initialized';
      notifyListeners();
      return false;
    }

    if (_isCollecting) {
      return true; // Already collecting
    }

    _isCollecting = true;
    _status = 'Collecting...';
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
      
      _status = 'Spectrum collection started';
      notifyListeners();
      
      return true;
    } catch (e) {
      if (kDebugMode) print('Failed to start spectrum collection with isolate: $e');
      _status = 'Failed to start collection: $e';
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
        _status = 'Collection error: ${message['message']}';
        
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
        _currentSpectrum = SpectrumData.fromRawAcquisition(
          wavelengths: wavelengths,
          intensities: intensities.map((e) => e.toInt()).toList(),
          timestamp: timestamp != null ? DateTime.parse(timestamp) : DateTime.now(),
          integrationTime: _integrationTime,
          scansToAverage: _scansToAverage,
          lastAcquisitionTime: lastAcquisitionTime,
          acquisitionStatus: acquisitionStatus,
        );
        
        // 处理染料含量和助剂含量数据
        final dyeContent = message['dyeContent'] as double?;
        final additiveContent = message['additiveContent'] as double?;
        
        if (dyeContent != null && lastAcquisitionTime != null) {
          await _processDyeContentData(dyeContent, lastAcquisitionTime);
        }
        
        if (additiveContent != null && lastAcquisitionTime != null) {
          await _processAdditiveContentData(additiveContent, lastAcquisitionTime);
        }
        
        // Save to file using frontend timestamp
        print('🔥 Saving spectrum data to file');
        try {
          final saveSuccess = await _fileService.saveSpectrumData(_currentSpectrum!);
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

  /// 处理染料含量数据
  Future<void> _processDyeContentData(double dyeContent, double lastAcquisitionTime) async {
    try {
      print('🎨 Processing dye content data: $dyeContent, acquisition_time: $lastAcquisitionTime');
      print('🎨 Last saved acquisition_time: $_lastSavedAcquisitionTime');
      
      // 检查是否为新的数据（基于acquisition_time）
      if (_lastSavedAcquisitionTime == null || _lastSavedAcquisitionTime != lastAcquisitionTime) {
        _currentDyeContent = DyeContentData(
          value: dyeContent,
          timestamp: DateTime.now(),
          lastAcquisitionTime: lastAcquisitionTime,
        );
        
        print('🎨 Created new dye content data: ${_currentDyeContent!.value}');
        
        // 添加到历史数据列表
        _historicalDyeContentData.add(_currentDyeContent!);
        
        // 限制历史数据数量（保留最近100个数据点）
        if (_historicalDyeContentData.length > 100) {
          _historicalDyeContentData.removeAt(0);
        }
        
        // 保存染料含量数据到CSV文件
        await _saveDyeContentData(_currentDyeContent!);
        
        // 更新上次保存的acquisition_time
        _lastSavedAcquisitionTime = lastAcquisitionTime;
        
        print('🎨 New dye content data saved: $dyeContent (acquisition_time: $lastAcquisitionTime)');
        
        // 立即通知UI更新染料含量数据
        notifyListeners();
      } else {
        print('🎨 Dye content data skipped - same acquisition_time: $lastAcquisitionTime');
      }
    } catch (e) {
      print('🎨 Error processing dye content data: $e');
    }
  }

  /// 处理助剂含量数据
  Future<void> _processAdditiveContentData(double additiveContent, double lastAcquisitionTime) async {
    try {
      print('🧪 Processing additive content data: $additiveContent, acquisition_time: $lastAcquisitionTime');
      print('🧪 Last saved acquisition_time: $_lastSavedAcquisitionTime');
      
      // 检查是否为新的数据（基于acquisition_time）
      if (_lastSavedAcquisitionTime == null || _lastSavedAcquisitionTime != lastAcquisitionTime) {
        _currentAdditiveContent = AdditiveContentData(
          value: additiveContent,
          timestamp: DateTime.now(),
          lastAcquisitionTime: lastAcquisitionTime,
        );
        
        print('🧪 Created new additive content data: ${_currentAdditiveContent!.value}');
        
        // 添加到历史数据列表
        _historicalAdditiveContentData.add(_currentAdditiveContent!);
        
        // 限制历史数据数量（保留最近100个数据点）
        if (_historicalAdditiveContentData.length > 100) {
          _historicalAdditiveContentData.removeAt(0);
        }
        
        // 保存助剂含量数据到CSV文件
        await _saveAdditiveContentData(_currentAdditiveContent!);
        
        // 更新上次保存的acquisition_time
        _lastSavedAcquisitionTime = lastAcquisitionTime;
        
        print('🧪 New additive content data saved: $additiveContent (acquisition_time: $lastAcquisitionTime)');
        
        // 立即通知UI更新助剂含量数据
        notifyListeners();
      } else {
        print('🧪 Additive content data skipped - same acquisition_time: $lastAcquisitionTime');
      }
    } catch (e) {
      print('🧪 Error processing additive content data: $e');
    }
  }

  /// 保存染料含量数据到文件
  Future<void> _saveDyeContentData(DyeContentData dyeContentData) async {
    try {
      final success = await _fileService.saveDyeContentData(dyeContentData);
      if (success) {
        print('🎨 Dye content data saved to file successfully');
      } else {
        print('🎨 Failed to save dye content data to file');
      }
    } catch (e) {
      print('🎨 Error saving dye content data: $e');
    }
  }

  /// 保存助剂含量数据到文件
  Future<void> _saveAdditiveContentData(AdditiveContentData additiveContentData) async {
    try {
      final success = await _fileService.saveAdditiveContentData(additiveContentData);
      if (success) {
        print('🧪 Additive content data saved to file successfully');
      } else {
        print('🧪 Failed to save additive content data to file');
      }
    } catch (e) {
      print('🧪 Error saving additive content data: $e');
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
    _status = 'Collection stopped';
    notifyListeners();
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
    _status = 'Resetting...';
    notifyListeners();
    
    try {
      final response = await _apiService.resetCDS350();
      if (response.success) {
        _status = 'Reset successful';
        notifyListeners();
        return await initializeDevice();
      } else {
        _status = 'Reset failed: ${response.message}';
        notifyListeners();
        return false;
      }
    } catch (e) {
      _status = 'Reset error: $e';
      notifyListeners();
      return false;
    }
  }

  /// Capture single spectrum
  Future<bool> captureSpectrum() async {
    if (!_isInitialized) {
      _status = 'Device not initialized';
      notifyListeners();
      return false;
    }

    try {
      _status = 'Capturing spectrum...';
      notifyListeners();

      final config = CDS350Config(
        integrationTime: _integrationTime,
        scansToAverage: _scansToAverage,
      );

      final response = await _apiService.captureSpectrum(config, zjType: _currentZjType);
      
      if (response.success && response.data != null) {
        _currentSpectrum = response.data!;
        
        // Process dye and additive content if available
        if (_currentSpectrum!.dyeContent != null && _currentSpectrum!.lastAcquisitionTime != null) {
          await _processDyeContentData(_currentSpectrum!.dyeContent!, _currentSpectrum!.lastAcquisitionTime!);
        }
        
        if (_currentSpectrum!.additiveContent != null && _currentSpectrum!.lastAcquisitionTime != null) {
          await _processAdditiveContentData(_currentSpectrum!.additiveContent!, _currentSpectrum!.lastAcquisitionTime!);
        }
        
        // Save to file
        await _fileService.saveSpectrumData(_currentSpectrum!);
        
        _status = 'Spectrum captured successfully';
        notifyListeners();
        return true;
      } else {
        _status = 'Capture failed: ${response.message}';
        notifyListeners();
        return false;
      }
    } catch (e) {
      _status = 'Capture error: $e';
      notifyListeners();
      return false;
    }
  }

  @override
  void dispose() {
    stopCollection();
    super.dispose();
  }
}
