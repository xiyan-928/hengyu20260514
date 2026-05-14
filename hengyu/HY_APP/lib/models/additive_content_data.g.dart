// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'additive_content_data.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

AdditiveContentData _$AdditiveContentDataFromJson(Map<String, dynamic> json) =>
    AdditiveContentData(
      value: (json['value'] as num).toDouble(),
      timestamp: DateTime.parse(json['timestamp'] as String),
      lastAcquisitionTime: (json['lastAcquisitionTime'] as num).toDouble(),
    );

Map<String, dynamic> _$AdditiveContentDataToJson(
        AdditiveContentData instance) =>
    <String, dynamic>{
      'value': instance.value,
      'timestamp': instance.timestamp.toIso8601String(),
      'lastAcquisitionTime': instance.lastAcquisitionTime,
    };
