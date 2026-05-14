// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'online_analysis.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

OnlineAnalysisBatchRequest _$OnlineAnalysisBatchRequestFromJson(
        Map<String, dynamic> json) =>
    OnlineAnalysisBatchRequest(
      rl1Name: json['rl1_name'] as String,
      rl2Name: json['rl2_name'] as String,
      rl3Name: json['rl3_name'] as String,
    );

Map<String, dynamic> _$OnlineAnalysisBatchRequestToJson(
        OnlineAnalysisBatchRequest instance) =>
    <String, dynamic>{
      'rl1_name': instance.rl1Name,
      'rl2_name': instance.rl2Name,
      'rl3_name': instance.rl3Name,
    };

OnlineAnalysisBatchData _$OnlineAnalysisBatchDataFromJson(
        Map<String, dynamic> json) =>
    OnlineAnalysisBatchData(
      rl1Name: json['rl1_name'] as String,
      rl2Name: json['rl2_name'] as String,
      rl3Name: json['rl3_name'] as String,
      status: json['status'] as String,
      timestamp: json['timestamp'] as String,
    );

Map<String, dynamic> _$OnlineAnalysisBatchDataToJson(
        OnlineAnalysisBatchData instance) =>
    <String, dynamic>{
      'rl1_name': instance.rl1Name,
      'rl2_name': instance.rl2Name,
      'rl3_name': instance.rl3Name,
      'status': instance.status,
      'timestamp': instance.timestamp,
    };

DyeContentPoint _$DyeContentPointFromJson(Map<String, dynamic> json) =>
    DyeContentPoint(
      timestamp: DateTime.parse(json['timestamp'] as String),
      rl1Content: (json['rl1_content'] as num).toDouble(),
      rl2Content: (json['rl2_content'] as num).toDouble(),
      rl3Content: (json['rl3_content'] as num).toDouble(),
    );

Map<String, dynamic> _$DyeContentPointToJson(DyeContentPoint instance) =>
    <String, dynamic>{
      'timestamp': instance.timestamp.toIso8601String(),
      'rl1_content': instance.rl1Content,
      'rl2_content': instance.rl2Content,
      'rl3_content': instance.rl3Content,
    };
