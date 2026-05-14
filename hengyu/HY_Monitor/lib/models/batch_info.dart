/// 与 `HY_Server/test1.py::list_device_batches` 返回的元素结构对齐。
class BatchInfo {
  BatchInfo({
    required this.batch,
    required this.count,
    this.filename,
    this.firstTime,
    this.lastTime,
    this.process = const <String, dynamic>{},
  });

  /// 批次号（即 CSV 文件名去后缀，已经过服务端 `_safe_generation_batch` 净化）。
  final String batch;
  final String? filename;
  final int count;
  final DateTime? firstTime;
  final DateTime? lastTime;

  /// 工艺参数原始 Map（生成批次、布重、布长宽高厚密度材料、浴比等）。
  final Map<String, dynamic> process;

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

  /// 下拉框中显示的标签：优先用 `generation_batch`，否则退回 batch 文件名。
  String get displayLabel {
    final gb = generationBatch;
    if (gb != null && gb.isNotEmpty) return gb;
    return batch;
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
