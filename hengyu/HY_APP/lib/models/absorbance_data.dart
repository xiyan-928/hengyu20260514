import 'package:json_annotation/json_annotation.dart';

part 'absorbance_data.g.dart';

@JsonSerializable()
class AbsorbanceData {
  final double value;
  final DateTime timestamp;
  final double lastAcquisitionTime; // API的acquisition_status.last_acquisition_time
  
  AbsorbanceData({
    required this.value,
    required this.timestamp,
    required this.lastAcquisitionTime,
  });

  factory AbsorbanceData.fromJson(Map<String, dynamic> json) =>
      _$AbsorbanceDataFromJson(json);

  Map<String, dynamic> toJson() => _$AbsorbanceDataToJson(this);

  /// Convert to CSV row format
  String toCsvRow() {
    return '${timestamp.toIso8601String()},$lastAcquisitionTime,$value';
  }

  /// CSV header
  static String csvHeader() {
    return 'Timestamp,AcquisitionTime,Absorbance';
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is AbsorbanceData &&
          runtimeType == other.runtimeType &&
          lastAcquisitionTime == other.lastAcquisitionTime;

  @override
  int get hashCode => lastAcquisitionTime.hashCode;
}
