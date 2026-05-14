// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'spectrum_data.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

SpectrumData _$SpectrumDataFromJson(Map<String, dynamic> json) => SpectrumData(
      wavelengths: (json['wavelengths'] as List<dynamic>)
          .map((e) => (e as num).toDouble())
          .toList(),
      intensities: (json['spectrum'] as List<dynamic>)
          .map((e) => (e as num).toInt())
          .toList(),
      timestamp: DateTime.parse(json['timestamp'] as String),
      length: (json['length'] as num).toInt(),
      integrationTime: (json['integration_time'] as num).toInt(),
      scansToAverage: (json['scans_to_average'] as num).toInt(),
      lastAcquisitionTime: (json['last_acquisition_time'] as num?)?.toDouble(),
      acquisitionStatus: json['acquisition_status'] as Map<String, dynamic>?,
    );

Map<String, dynamic> _$SpectrumDataToJson(SpectrumData instance) =>
    <String, dynamic>{
      'wavelengths': instance.wavelengths,
      'spectrum': instance.intensities,
      'timestamp': instance.timestamp.toIso8601String(),
      'length': instance.length,
      'integration_time': instance.integrationTime,
      'scans_to_average': instance.scansToAverage,
      'last_acquisition_time': instance.lastAcquisitionTime,
      'acquisition_status': instance.acquisitionStatus,
    };
