/// 光谱数据：波长轴固定为整数 nm [acquisitionWavelengthMinNm, acquisitionWavelengthMaxNm]，
/// 仅 [intensities] 按顺序存储各波长强度（与 toJson 一致，不包含 wavelengths 字段）。
class SpectrumData {
  /// 采集光谱固定区间起点（nm，整数，含端点）。
  static const int acquisitionWavelengthMinNm = 200;

  /// 采集光谱固定区间终点（nm，整数，含端点）。
  static const int acquisitionWavelengthMaxNm = 1100;

  /// 固定通道数：200..1100 共 901 个点。
  static const int acquisitionChannelCount =
      acquisitionWavelengthMaxNm - acquisitionWavelengthMinNm + 1;

  /// 长度须为 [acquisitionChannelCount]；[i] 对应波长 nm = [acquisitionWavelengthMinNm] + i。
  final List<int> intensities;
  final DateTime timestamp;
  final int length;
  final int integrationTime;
  final int scansToAverage;
  final double? lastAcquisitionTime;
  final Map<String, dynamic>? acquisitionStatus;

  SpectrumData({
    required this.intensities,
    required this.timestamp,
    required this.length,
    required this.integrationTime,
    required this.scansToAverage,
    this.lastAcquisitionTime,
    this.acquisitionStatus,
  }) : assert(intensities.length == acquisitionChannelCount);

  factory SpectrumData.fromJson(Map<String, dynamic> json) {
    final timestamp = json['timestamp'] != null
        ? DateTime.parse(json['timestamp'] as String)
        : DateTime.now();
    final integrationTime =
        (json['integration_time'] as num?)?.toInt() ?? 10000;
    final scansToAverage = (json['scans_to_average'] as num?)?.toInt() ?? 3;
    final lastAcquisitionTime =
        (json['last_acquisition_time'] as num?)?.toDouble();
    final acquisitionStatus =
        json['acquisition_status'] as Map<String, dynamic>?;

    List<int> grid;
    final sp = json['spectrum'] ?? json['intensities'];
    if (sp is List && sp.isNotEmpty) {
      final rawI = sp.map((e) => (e as num).toInt()).toList();
      final wlRaw = json['wavelengths'];
      if (wlRaw is List && wlRaw.length == rawI.length) {
        final wl = wlRaw.map((e) => (e as num).toDouble()).toList();
        grid = buildAcquisitionIntensityGrid(wl, rawI);
      } else {
        if (rawI.length == acquisitionChannelCount) {
          grid = List<int>.from(rawI);
        } else {
          final wl = List<double>.generate(
            rawI.length,
            (i) => (acquisitionWavelengthMinNm + i).toDouble(),
          );
          grid = buildAcquisitionIntensityGrid(wl, rawI);
        }
      }
    } else {
      grid = List<int>.filled(acquisitionChannelCount, 0);
    }

    final length = (json['length'] as num?)?.toInt() ?? grid.length;

    return SpectrumData(
      intensities: grid,
      timestamp: timestamp,
      length: length,
      integrationTime: integrationTime,
      scansToAverage: scansToAverage,
      lastAcquisitionTime: lastAcquisitionTime,
      acquisitionStatus: acquisitionStatus,
    );
  }

  /// API / 持久化 JSON：仅包含强度序列及元数据（不含 wavelengths）。
  Map<String, dynamic> toJson() => <String, dynamic>{
        'spectrum': intensities,
        'timestamp': timestamp.toIso8601String(),
        'length': length,
        'integration_time': integrationTime,
        'scans_to_average': scansToAverage,
        if (lastAcquisitionTime != null)
          'last_acquisition_time': lastAcquisitionTime,
        if (acquisitionStatus != null) 'acquisition_status': acquisitionStatus,
      };

  /// 第 [index] 通道对应的波长（nm，整数，与设备网格一致）。
  double wavelengthAt(int index) =>
      (acquisitionWavelengthMinNm + index).toDouble();

  /// 与 [intensities] 等长的 X 轴（nm），便于绑图或调试。
  List<double> get wavelengthAxis => List<double>.generate(
        intensities.length,
        (i) => (acquisitionWavelengthMinNm + i).toDouble(),
      );

  /// 将原始波长-强度填充到固定网格；相同整数 nm 保留最后一次；强度取整；区间外丢弃。
  static List<int> buildAcquisitionIntensityGrid(
    List<double> wavelengths,
    List<int> intensities,
  ) {
    final grid = List<int>.filled(acquisitionChannelCount, 0);
    final n = wavelengths.length < intensities.length
        ? wavelengths.length
        : intensities.length;
    for (var i = 0; i < n; i++) {
      final nm = wavelengths[i].truncate().toInt();
      if (nm < acquisitionWavelengthMinNm || nm > acquisitionWavelengthMaxNm) {
        continue;
      }
      grid[nm - acquisitionWavelengthMinNm] = intensities[i].truncate().toInt();
    }
    return grid;
  }

  /// 同 [buildAcquisitionIntensityGrid]，返回新的 [SpectrumData]。
  SpectrumData withNormalizedAcquisitionSeries() {
    final g = buildAcquisitionIntensityGrid(
      List<double>.generate(
        intensities.length,
        (i) => (acquisitionWavelengthMinNm + i).toDouble(),
      ),
      intensities,
    );
    return SpectrumData(
      intensities: g,
      timestamp: timestamp,
      length: g.length,
      integrationTime: integrationTime,
      scansToAverage: scansToAverage,
      lastAcquisitionTime: lastAcquisitionTime,
      acquisitionStatus: acquisitionStatus,
    );
  }

  /// 从单次采集的原始序列构造（先写入固定网格）。
  factory SpectrumData.fromRawAcquisition({
    required List<double> wavelengths,
    required List<int> intensities,
    required DateTime timestamp,
    required int integrationTime,
    required int scansToAverage,
    double? lastAcquisitionTime,
    Map<String, dynamic>? acquisitionStatus,
  }) {
    final grid = buildAcquisitionIntensityGrid(wavelengths, intensities);
    return SpectrumData(
      intensities: grid,
      timestamp: timestamp,
      length: grid.length,
      integrationTime: integrationTime,
      scansToAverage: scansToAverage,
      lastAcquisitionTime: lastAcquisitionTime,
      acquisitionStatus: acquisitionStatus,
    );
  }

  /// CSV：仍输出 wavelength,intensity 两列（波长由网格隐含导出）。
  String toCsv() {
    final buffer = StringBuffer()..writeln('wavelength,intensity');
    for (var i = 0; i < intensities.length; i++) {
      buffer.writeln('${acquisitionWavelengthMinNm + i},${intensities[i]}');
    }
    return buffer.toString();
  }
}
