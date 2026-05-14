import 'spc_file_info.dart';

/// 对应 `GET /spc/search` 返回的单条结果。
class SpcSearchResult {
  SpcSearchResult({
    required this.deviceId,
    required this.spcType,
    required this.fileInfo,
  });

  final String deviceId;

  /// 'sample' | 'blank_before' | 'blank_after'
  final String spcType;

  final SpcFileInfo fileInfo;

  factory SpcSearchResult.fromJson(Map<String, dynamic> json) {
    return SpcSearchResult(
      deviceId: (json['device_id'] ?? '').toString(),
      spcType: (json['spc_type'] ?? 'sample').toString(),
      fileInfo: SpcFileInfo.fromJson(json),
    );
  }

  String get typeLabel => switch (spcType) {
        'blank_before' => '置换前参比',
        'blank_after' => '清洗后参比',
        _ => '采样光谱',
      };
}
