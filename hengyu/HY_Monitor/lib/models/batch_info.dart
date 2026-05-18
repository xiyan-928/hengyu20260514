/// 生成单号下拉框「条数」含义：历史页用传感器条数，SPC 页用采样光谱文件条数，参比页用参比光谱条数。
enum BatchSidebarCountKind {
  sensor,
  spectrumSample,
  blankReference,
}

/// 与 `HY_Server/test1.py::list_device_batches` 返回的元素结构对齐。
class BatchInfo {
  BatchInfo({
    required this.batch,
    required this.count,
    this.filename,
    this.firstTime,
    this.lastTime,
    this.process = const <String, dynamic>{},
    this.spectrumFileCount = 0,
    this.blankSpcFileCount = 0,
  });

  /// 单号（即 CSV 文件名去后缀，已经过服务端 `_safe_generation_batch` 净化）。
  final String batch;
  final String? filename;
  final int count;
  final DateTime? firstTime;
  final DateTime? lastTime;

  /// 工艺参数原始 Map（生成单号、布重、布长宽高厚密度材料、浴比等）。
  final Map<String, dynamic> process;

  /// 该单号下 `spc_store` 采样光谱文件数（与 `GET /spc/device/{id}` 列表一致，不含暗光谱）。
  final int spectrumFileCount;

  /// 该单号下全部类型的参比光谱文件总数。
  final int blankSpcFileCount;

  String? get generationBatch =>
      (process['generation_batch'] as Object?)?.toString();
  double? get fabricWeightG => _asDouble(process['fabric_weight_g']);
  double? get fabricLength => _asDouble(process['fabric_length']);
  double? get fabricWidth => _asDouble(process['fabric_width']);
  double? get fabricHeight => _asDouble(process['fabric_height']);
  double? get fabricThickness => _asDouble(process['fabric_thickness']);
  double? get fabricDensity => _asDouble(process['fabric_density']);
  String? get fabricMaterial =>
      (process['fabric_material'] as Object?)?.toString();
  double? get bathRatio => _asDouble(process['bath_ratio']);

  /// 下拉框中显示的标签：优先用 `generation_batch`（单号），否则退回 CSV 文件名。
  String get displayLabel {
    final gb = generationBatch;
    if (gb != null && gb.isNotEmpty) return gb;
    return batch;
  }

  /// 侧栏「生成单号」下拉项中单号后的条数。
  int countForSidebar(BatchSidebarCountKind kind) {
    switch (kind) {
      case BatchSidebarCountKind.sensor:
        return count;
      case BatchSidebarCountKind.spectrumSample:
        return spectrumFileCount;
      case BatchSidebarCountKind.blankReference:
        return blankSpcFileCount;
    }
  }

  factory BatchInfo.fromJson(Map<String, dynamic> j) {
    return BatchInfo(
      batch: (j['batch'] ?? '').toString(),
      filename: j['filename']?.toString(),
      count: _asInt(j['count']) ?? 0,
      firstTime: _parseTime(j['first_time']?.toString()),
      lastTime: _parseTime(j['last_time']?.toString()),
      process: (j['process'] is Map)
          ? Map<String, dynamic>.from(j['process'] as Map)
          : const <String, dynamic>{},
      spectrumFileCount: _asInt(j['spectrum_file_count']) ?? 0,
      blankSpcFileCount: _asInt(j['blank_spc_file_count']) ?? 0,
    );
  }

  static DateTime? _parseTime(String? s) {
    if (s == null || s.isEmpty) return null;
    try {
      return DateTime.parse(s.replaceFirst(' ', 'T'));
    } catch (_) {
      return null;
    }
  }

  static double? _asDouble(dynamic v) {
    if (v == null) return null;
    if (v is num) return v.toDouble();
    if (v is String) return double.tryParse(v);
    return null;
  }

  static int? _asInt(dynamic v) {
    if (v == null) return null;
    if (v is int) return v;
    if (v is num) return v.toInt();
    if (v is String) return int.tryParse(v);
    return null;
  }
}
