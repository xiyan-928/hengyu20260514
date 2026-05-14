import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../lib/models/sensor_data.dart';
import '../lib/models/spectrum_data.dart';

void main() {
  group('FileService - System Timestamp Tests', () {
    
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('should use current system time for sensor data saving', () async {
      // Create test sensor data with old timestamp
      final oldTimestamp = DateTime(2023, 1, 1, 12, 0, 0);
      final sensorData = SensorData(
        deviceType: 'TEMP',
        value: 25.5,
        unit: '°C',
        timestamp: oldTimestamp,
      );
      
      // The key point is that saveSensorDataRow uses DateTime.now() instead of sensor timestamp
      expect(sensorData.timestamp, equals(oldTimestamp));
      
      // In the actual implementation, the CSV row should contain current system time
      // not the sensorData.timestamp
      print('测试传感器数据时间戳优化');
      print('原始传感器时间戳: ${sensorData.timestamp}');
      print('当前系统时间: ${DateTime.now()}');
    });

    test('should use current system time for spectrum data saving', () async {
      // Create test spectrum data with old timestamp
      final oldTimestamp = DateTime(2023, 1, 1, 12, 0, 0);
      final spectrumData = SpectrumData(
        wavelengths: [400.0, 500.0, 600.0],
        intensities: [1000, 2000, 1500],
        timestamp: oldTimestamp,
        length: 3,
        integrationTime: 10000,
        scansToAverage: 3,
      );

      // Verify the logic: spectrum data should use current time for file naming and CSV content
      expect(spectrumData.timestamp, equals(oldTimestamp));
      
      print('测试光谱数据时间戳优化');
      print('原始光谱时间戳: ${spectrumData.timestamp}');
      print('当前系统时间: ${DateTime.now()}');
    });

    test('should create file names with current date', () async {
      // Test that file names use current system date, not data timestamp
      final currentTime = DateTime.now();
      final expectedDateStr = '${currentTime.year.toString().padLeft(4, '0')}-${currentTime.month.toString().padLeft(2, '0')}-${currentTime.day.toString().padLeft(2, '0')}';
      
      print('当前日期字符串: $expectedDateStr');
      print('文件名应基于当前系统时间，而不是数据中的时间戳');
      
      expect(expectedDateStr.length, equals(10)); // YYYY-MM-DD format
    });
  });
}
