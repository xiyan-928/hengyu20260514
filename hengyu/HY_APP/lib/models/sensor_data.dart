import 'package:json_annotation/json_annotation.dart';

part 'sensor_data.g.dart';

@JsonSerializable()
class SensorData {
  final String deviceType;
  final double value;
  final String unit;
  final DateTime timestamp;
  final String? deviceIp;
  final int? devicePort;

  SensorData({
    required this.deviceType,
    required this.value,
    required this.unit,
    required this.timestamp,
    this.deviceIp,
    this.devicePort,
  });

  factory SensorData.fromJson(Map<String, dynamic> json) =>
      _$SensorDataFromJson(json);

  Map<String, dynamic> toJson() => _$SensorDataToJson(this);

  /// Convert to CSV row format for unified sensor data
  String toCsvRow() {
    return '${timestamp.toIso8601String()},$deviceType,$value,$unit,${deviceIp ?? ''},$devicePort';
  }

  /// Get CSV header for individual sensor files
  static String getCsvHeader() {
    return 'Timestamp,Device Type,Value,Unit,Device IP,Device Port';
  }

  /// Convert list of sensor data to unified CSV format
  /// Columns: Date, Sensor1, Sensor2, Sensor3, Sensor4, ...
  static String toUnifiedCsv(List<SensorData> sensorDataList) {
    if (sensorDataList.isEmpty) return '';
    
    // Group data by timestamp (date part only)
    final Map<String, Map<String, double>> groupedData = {};
    final Set<String> allSensorTypes = {};
    
    for (final data in sensorDataList) {
      final dateKey = data.timestamp.toIso8601String().substring(0, 10); // YYYY-MM-DD
      allSensorTypes.add(data.deviceType);
      
      if (!groupedData.containsKey(dateKey)) {
        groupedData[dateKey] = {};
      }
      groupedData[dateKey]![data.deviceType] = data.value;
    }
    
    // Create header
    final sensorTypesList = allSensorTypes.toList()..sort();
    final header = ['Date', ...sensorTypesList].join(',');
    
    // Create data rows
    final rows = <String>[header];
    final sortedDates = groupedData.keys.toList()..sort();
    
    for (final date in sortedDates) {
      final rowData = [date];
      for (final sensorType in sensorTypesList) {
        final value = groupedData[date]![sensorType];
        rowData.add(value?.toString() ?? '');
      }
      rows.add(rowData.join(','));
    }
    
    return rows.join('\n');
  }

  /// Get unified CSV header for given sensor types
  static String getUnifiedCsvHeader(List<String> sensorTypes) {
    final sortedTypes = sensorTypes.toList()..sort();
    return ['Date', ...sortedTypes].join(',');
  }
}
