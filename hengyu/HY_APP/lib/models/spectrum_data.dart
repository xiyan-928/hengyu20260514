import 'package:json_annotation/json_annotation.dart';

part 'spectrum_data.g.dart';

@JsonSerializable()
class SpectrumData {
  final List<double> wavelengths;
  @JsonKey(name: 'spectrum')
  final List<int> intensities;
  final DateTime timestamp;
  final int length;
  @JsonKey(name: 'integration_time')
  final int integrationTime;
  @JsonKey(name: 'scans_to_average')
  final int scansToAverage;
  @JsonKey(name: 'last_acquisition_time')
  final double? lastAcquisitionTime;
  @JsonKey(name: 'acquisition_status')
  final Map<String, dynamic>? acquisitionStatus;

  SpectrumData({
    required this.wavelengths,
    required this.intensities,
    required this.timestamp,
    required this.length,
    required this.integrationTime,
    required this.scansToAverage,
    this.lastAcquisitionTime,
    this.acquisitionStatus,
  });

  factory SpectrumData.fromJson(Map<String, dynamic> json) =>
      _$SpectrumDataFromJson(json);

  Map<String, dynamic> toJson() => _$SpectrumDataToJson(this);

  /// Convert to CSV format for file export
  String toCsv() {
    final buffer = StringBuffer();

    buffer.writeln('wavelength,intensity');

    for (int i = 0; i < wavelengths.length && i < intensities.length; i++) {
      buffer.writeln('${wavelengths[i]},${intensities[i]}');
    }

    return buffer.toString();
  }
}
