/// 对应 test1.py `GET /spc/device/{id}` 返回的单条记录。
class SpcFileInfo {
  SpcFileInfo({
    required this.originalFilename,
    required this.storedFilename,
    required this.size,
    required this.serverTime,
    this.batch,
    this.kind,
    this.blankType,
  });

  final String originalFilename;
  final String storedFilename;
  final int size;

  /// 服务器上传时间字符串，格式 "YYYY-MM-DD HH:MM:SS"。
  final String serverTime;
  final String? batch;
  final String? kind;
  final String? blankType;

  factory SpcFileInfo.fromJson(Map<String, dynamic> json) {
    return SpcFileInfo(
      originalFilename: (json['original_filename'] ?? '').toString(),
      storedFilename: (json['stored_filename'] ?? '').toString(),
      size: _toInt(json['size']),
      serverTime: (json['server_time'] ?? '').toString(),
      batch: _toOptionalString(json['batch']),
      kind: _toOptionalString(json['kind']),
      blankType: _toOptionalString(json['blank_type']),
    );
  }

  /// 将 [serverTime] 解析为 [DateTime]，解析失败时返回 null。
  DateTime? get serverDate {
    if (serverTime.isEmpty) return null;
    try {
      // "YYYY-MM-DD HH:MM:SS" → "YYYY-MM-DDTHH:MM:SS"
      return DateTime.parse(serverTime.replaceFirst(' ', 'T'));
    } catch (_) {
      return null;
    }
  }

  String get readableSize {
    if (size >= 1024 * 1024) return '${(size / 1024 / 1024).toStringAsFixed(2)} MB';
    if (size >= 1024) return '${(size / 1024).toStringAsFixed(1)} KB';
    return '$size B';
  }

  static int _toInt(dynamic v, {int fallback = 0}) {
    if (v is int) return v;
    if (v is num) return v.toInt();
    if (v is String) return int.tryParse(v) ?? fallback;
    return fallback;
  }

  static String? _toOptionalString(dynamic v) {
    if (v == null) return null;
    final s = v.toString();
    return s.isEmpty ? null : s;
  }
}
