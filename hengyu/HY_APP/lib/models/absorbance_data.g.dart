// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'absorbance_data.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

AbsorbanceData _$AbsorbanceDataFromJson(Map<String, dynamic> json) =>
    AbsorbanceData(
      value: (json['value'] as num).toDouble(),
      timestamp: DateTime.parse(json['timestamp'] as String),
      lastAcquisitionTime: (json['lastAcquisitionTime'] as num).toDouble(),
    );

Map<String, dynamic> _$AbsorbanceDataToJson(AbsorbanceData instance) =>
    <String, dynamic>{
      'value': instance.value,
      'timestamp': instance.timestamp.toIso8601String(),
      'lastAcquisitionTime': instance.lastAcquisitionTime,
    };
