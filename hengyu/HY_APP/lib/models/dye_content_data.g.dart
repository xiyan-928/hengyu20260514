// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'dye_content_data.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

DyeContentData _$DyeContentDataFromJson(Map<String, dynamic> json) =>
    DyeContentData(
      value: (json['value'] as num).toDouble(),
      timestamp: DateTime.parse(json['timestamp'] as String),
      lastAcquisitionTime: (json['lastAcquisitionTime'] as num).toDouble(),
    );

Map<String, dynamic> _$DyeContentDataToJson(DyeContentData instance) =>
    <String, dynamic>{
      'value': instance.value,
      'timestamp': instance.timestamp.toIso8601String(),
      'lastAcquisitionTime': instance.lastAcquisitionTime,
    };
