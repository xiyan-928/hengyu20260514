class AppConfig {
  // API Configuration
  static const String baseUrl = 'http://localhost:8000';
  static const Duration apiTimeout = Duration(seconds: 10);
  
  // Default Device Settings
  static const String defaultDeviceIp = '192.168.1.100';
  static const int defaultDevicePort = 502;
  
  // Default CDS350 Settings
  static const int defaultIntegrationTime = 10000; // microseconds
  static const int defaultScansToAverage = 3;
  static const int defaultSpectrumCollectionInterval = 1000; // milliseconds
  
  // Default Sensor Settings
  static const int defaultSensorCollectionInterval = 5000; // milliseconds
  
  //----------------------------------------
  /// 为 true 时，传感器/光谱任一路开始连续采集时调用 POST /api/upload-relay/start，供独立进程 upload_client_example 轮询后实际上传；两路都停止时 POST /api/upload-relay/stop。
  static const bool linkUploadRelayToCollection = true;

  // File Management
  static const String spectrumFilePrefix = 'SPEC';
  static const String sensorFileName = 'SENSOR.csv';
  static const int defaultDataRetentionDays = 30;
  
  // UI Configuration
  static const double defaultSpectrumChartHeight = 350;
  static const Duration statusUpdateInterval = Duration(milliseconds: 500);
  
  // Validation Limits
  static const int minIntegrationTime = 1000; // 1ms
  static const int maxIntegrationTime = 3600000000; // 1 hour
  static const int minScansToAverage = 1;
  static const int maxScansToAverage = 1000;
  static const int minCollectionInterval = 100; // 100ms
  static const int maxCollectionInterval = 3600000; // 1 hour
  
  // Device Types and Units
  static const Map<String, String> deviceUnits = {
    'PH': 'pH',
    'TEMP': '°C',
    'PT100': '°C',
    'DDL': 'mg/L',
  };
  
  static const Map<String, String> deviceDisplayNames = {
    'PH': 'pH Value',
    'TEMP': 'Temperature',
    'PT100': 'PT100 Temp',
    'DDL': 'Dissolved O₂',
  };
  
  // Alert Thresholds
  static const Map<String, Map<String, double>> alertThresholds = {
    'PH': {'min': 6.5, 'max': 8.5},
    'TEMP': {'min': 0, 'max': 50},
    'PT100': {'min': 0, 'max': 50},
    'DDL': {'min': 2, 'max': 20},
  };
}
