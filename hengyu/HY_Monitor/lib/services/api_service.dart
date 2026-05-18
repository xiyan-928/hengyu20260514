import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../app_config.dart';
import '../models/batch_info.dart';
import '../models/device_data.dart';
import '../models/spc_file_info.dart';
import '../models/spc_search_result.dart';
import '../models/spectrum_data.dart';

/// 封装 HY_Online/test1.py 的所有 REST 端点。
///
/// 所有异常统一抛 [ApiException]，上层（Provider/UI）只需 try/catch 一次。
class ApiService {
  ApiService(this._baseUrl);

  String _baseUrl;

  set baseUrl(String value) => _baseUrl = value.trim();
  String get baseUrl => _baseUrl;

  Duration get _timeout => const Duration(seconds: AppConfig.httpTimeoutSec);

  Uri _u(String path) {
    final base = _baseUrl.replaceAll(RegExp(r'/+$'), '');
    return Uri.parse('$base$path');
  }

  // --------------------------------------------------------------------------
  // 设备快照
  // --------------------------------------------------------------------------

  Future<List<String>> listDevices() async {
    final resp = await _get('/devices');
    final body = _decode(resp);
    final devices = body['devices'];
    if (devices is List) {
      return devices.map((e) => e.toString()).toList();
    }
    return const [];
  }

  /// `GET /device/{id}/latest`
  Future<DeviceData> getLatest(String deviceId) async {
    final resp = await _get('/device/${Uri.encodeComponent(deviceId)}/latest');
    final body = _decode(resp);
    return DeviceData.fromJson(body);
  }

  /// `GET /device/{id}` 返回 `{device_id, count, data:[...]}`。
  Future<List<DeviceData>> getHistory(String deviceId) async {
    final resp = await _get('/device/${Uri.encodeComponent(deviceId)}');
    final body = _decode(resp);
    final data = body['data'];
    if (data is List) {
      return data
          .whereType<Map>()
          .map((e) => DeviceData.fromJson(Map<String, dynamic>.from(e)))
          .toList();
    }
    return const [];
  }

  /// `GET /device/{id}/batches` — 列出该设备已落盘的所有生产单号（CSV 粒度）。
  Future<List<BatchInfo>> listBatches(String deviceId) async {
    final resp = await _get('/device/${Uri.encodeComponent(deviceId)}/batches');
    final body = _decode(resp);
    final batches = body['batches'];
    if (batches is List) {
      return batches
          .whereType<Map>()
          .map((e) => BatchInfo.fromJson(Map<String, dynamic>.from(e)))
          .toList();
    }
    return const [];
  }

  /// `GET /device/{id}/batch/{batch}` — 加载某个单号对应 CSV 的全部历史记录。
  Future<List<DeviceData>> getBatchHistory(
    String deviceId,
    String batch,
  ) async {
    final resp = await _get(
      '/device/${Uri.encodeComponent(deviceId)}'
      '/batch/${Uri.encodeComponent(batch)}',
    );
    final body = _decode(resp);
    final data = body['data'];
    if (data is List) {
      return data
          .whereType<Map>()
          .map((e) => DeviceData.fromJson(Map<String, dynamic>.from(e)))
          .toList();
    }
    return const [];
  }

  // --------------------------------------------------------------------------
  // SPC 文件
  // --------------------------------------------------------------------------

  /// `GET /spc/device/{id}`。若 404（当前无 SPC）返回空列表，而不是抛异常。
  ///
  /// 可通过 [dateFrom] / [dateTo] 在服务端按上传日期过滤（格式 YYYY-MM-DD）。
  Future<List<SpcFileInfo>> listSpcFiles(
    String deviceId, {
    String? batch,
    DateTime? dateFrom,
    DateTime? dateTo,
  }) async {
    final params = <String, String>{};
    if (batch != null && batch.isNotEmpty) params['batch'] = batch;
    if (dateFrom != null) params['date_from'] = _fmtDate(dateFrom);
    if (dateTo != null) params['date_to'] = _fmtDate(dateTo);

    final base = _u('/spc/device/${Uri.encodeComponent(deviceId)}');
    final uri = params.isEmpty ? base : base.replace(queryParameters: params);
    try {
      final resp = await http.get(uri).timeout(_timeout);
      if (resp.statusCode == 404) return const [];
      _ensureOk(resp);
      final body = _decode(resp);
      final files = body['files'];
      if (files is List) {
        return files
            .whereType<Map>()
            .map((e) => SpcFileInfo.fromJson(Map<String, dynamic>.from(e)))
            .toList();
      }
      return const [];
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException('获取 SPC 文件列表失败: $e');
    }
  }

  /// 下载最新 SPC 文件内容，返回 (filename, bytes)。
  Future<(String, Uint8List)> downloadLatestSpc(
    String deviceId, {
    String? batch,
  }) {
    final base = _u('/spc/device/${Uri.encodeComponent(deviceId)}/latest');
    final uri = (batch == null || batch.isEmpty)
        ? base
        : base.replace(queryParameters: {'batch': batch});
    return _downloadSpcUri(uri);
  }

  /// 按文件名下载指定 SPC。
  Future<(String, Uint8List)> downloadSpcByName(
    String deviceId,
    String filename, {
    String? batch,
  }) {
    final base = _u(
      '/spc/device/${Uri.encodeComponent(deviceId)}/files/${Uri.encodeComponent(filename)}',
    );
    final uri = (batch == null || batch.isEmpty)
        ? base
        : base.replace(queryParameters: {'batch': batch});
    return _downloadSpcUri(uri);
  }

  /// 获取指定采样 SPC 文件的横纵坐标数据。
  Future<SpectrumData> getSpcSpectrumData(
    String deviceId,
    String filename, {
    String? batch,
  }) async {
    final base = _u(
      '/spc/device/${Uri.encodeComponent(deviceId)}/files/${Uri.encodeComponent(filename)}/data',
    );
    final uri = (batch == null || batch.isEmpty)
        ? base
        : base.replace(queryParameters: {'batch': batch});
    final body = await _getJsonUri(uri, '获取 SPC 光谱数据失败');
    return SpectrumData.fromJson(body);
  }

  // --------------------------------------------------------------------------
  // 参比光谱 SPC 文件（blank_before / blank_after）
  // --------------------------------------------------------------------------

  /// `GET /spc/blank/device/{id}`
  /// 返回 `{blank_type: List<SpcFileInfo>}`；若 404（尚无记录）返回空 Map。
  ///
  /// 可通过 [dateFrom] / [dateTo] 在服务端按上传日期过滤（格式 YYYY-MM-DD）。
  Future<Map<String, List<SpcFileInfo>>> listBlankSpcFiles(
    String deviceId, {
    String? batch,
    DateTime? dateFrom,
    DateTime? dateTo,
  }) async {
    final params = <String, String>{};
    if (batch != null && batch.isNotEmpty) params['batch'] = batch;
    if (dateFrom != null) params['date_from'] = _fmtDate(dateFrom);
    if (dateTo != null) params['date_to'] = _fmtDate(dateTo);

    final base = _u('/spc/blank/device/${Uri.encodeComponent(deviceId)}');
    final uri = params.isEmpty ? base : base.replace(queryParameters: params);
    try {
      final resp = await http.get(uri).timeout(_timeout);
      if (resp.statusCode == 404) return const {};
      _ensureOk(resp);
      final body = _decode(resp);
      final blankTypes = body['blank_types'];
      if (blankTypes is! Map) return const {};
      return blankTypes.map((key, value) {
        final files = (value is Map ? value['files'] : null);
        final list = files is List
            ? files
                .whereType<Map>()
                .map((e) => SpcFileInfo.fromJson(Map<String, dynamic>.from(e)))
                .toList()
            : <SpcFileInfo>[];
        return MapEntry(key.toString(), list);
      });
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException('获取参比光谱文件列表失败: $e');
    }
  }

  /// `GET /spc/blank/device/{id}/{blank_type}/latest` — 下载最新参比光谱 SPC。
  Future<(String, Uint8List)> downloadLatestBlankSpc(
    String deviceId,
    String blankType, {
    String? batch,
  }) {
    final base = _u(
      '/spc/blank/device/${Uri.encodeComponent(deviceId)}'
      '/${Uri.encodeComponent(blankType)}/latest',
    );
    final uri = (batch == null || batch.isEmpty)
        ? base
        : base.replace(queryParameters: {'batch': batch});
    return _downloadSpcUri(uri);
  }

  /// `GET /spc/blank/device/{id}/{blank_type}/files/{filename}` — 按文件名下载。
  Future<(String, Uint8List)> downloadBlankSpcByName(
    String deviceId,
    String blankType,
    String filename, {
    String? batch,
  }) {
    final base = _u(
      '/spc/blank/device/${Uri.encodeComponent(deviceId)}'
      '/${Uri.encodeComponent(blankType)}'
      '/files/${Uri.encodeComponent(filename)}',
    );
    final uri = (batch == null || batch.isEmpty)
        ? base
        : base.replace(queryParameters: {'batch': batch});
    return _downloadSpcUri(uri);
  }

  /// 获取指定参比 SPC 文件的横纵坐标数据。
  Future<SpectrumData> getBlankSpcSpectrumData(
    String deviceId,
    String blankType,
    String filename, {
    String? batch,
  }) async {
    final base = _u(
      '/spc/blank/device/${Uri.encodeComponent(deviceId)}'
      '/${Uri.encodeComponent(blankType)}'
      '/files/${Uri.encodeComponent(filename)}/data',
    );
    final uri = (batch == null || batch.isEmpty)
        ? base
        : base.replace(queryParameters: {'batch': batch});
    final body = await _getJsonUri(uri, '获取参比光谱数据失败');
    return SpectrumData.fromJson(body);
  }

  Future<(String, Uint8List)> _downloadSpc(String path) async {
    return _downloadSpcUri(_u(path));
  }

  Future<(String, Uint8List)> _downloadSpcUri(Uri uri) async {
    try {
      final resp = await http.get(uri).timeout(_timeout);
      _ensureOk(resp);
      final cd = resp.headers['content-disposition'] ?? '';
      final match = RegExp(r'filename="?([^";]+)"?').firstMatch(cd);
      final filename = match?.group(1) ?? 'download.spc';
      return (filename, resp.bodyBytes);
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException('下载 SPC 文件失败: $e');
    }
  }

  Future<Map<String, dynamic>> _getJson(String path, String errorPrefix) async {
    return _getJsonUri(_u(path), errorPrefix);
  }

  Future<Map<String, dynamic>> _getJsonUri(Uri uri, String errorPrefix) async {
    try {
      final resp = await http.get(uri).timeout(_timeout);
      _ensureOk(resp);
      return _decode(resp);
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException('$errorPrefix: $e');
    }
  }

  // --------------------------------------------------------------------------
  // 光谱跨设备检索
  // --------------------------------------------------------------------------

  /// `GET /spc/search` — 按日期 / 设备 / 类型跨设备检索 SPC 文件，结果按时间降序。
  ///
  /// [spcType]: null = 全部；'sample' / 'blank_before' / 'blank_after'
  Future<List<SpcSearchResult>> searchSpc({
    DateTime? dateFrom,
    DateTime? dateTo,
    String? deviceId,
    String? spcType,
  }) async {
    final params = <String, String>{};
    if (dateFrom != null) params['date_from'] = _fmtDate(dateFrom);
    if (dateTo != null) params['date_to'] = _fmtDate(dateTo);
    if (deviceId != null && deviceId.isNotEmpty) params['device_id'] = deviceId;
    if (spcType != null && spcType.isNotEmpty) params['spc_type'] = spcType;

    final base = _u('/spc/search');
    final uri = params.isEmpty ? base : base.replace(queryParameters: params);
    try {
      final resp = await http.get(uri).timeout(_timeout);
      _ensureOk(resp);
      final body = _decode(resp);
      final results = body['results'];
      if (results is List) {
        return results
            .whereType<Map>()
            .map((e) => SpcSearchResult.fromJson(Map<String, dynamic>.from(e)))
            .toList();
      }
      return const [];
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException('光谱检索失败: $e');
    }
  }

  // --------------------------------------------------------------------------
  // 上传（主要给联调/自测用，正式边缘端走 upload_client_example.py）
  // --------------------------------------------------------------------------

  Future<Map<String, dynamic>> uploadDeviceData(DeviceData data) async {
    final uri = _u('/upload');
    try {
      final resp = await http
          .post(
            uri,
            headers: const {'Content-Type': 'application/json'},
            body: jsonEncode(data.toUploadJson()),
          )
          .timeout(_timeout);
      _ensureOk(resp);
      return _decode(resp);
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException('上传传感器数据失败: $e');
    }
  }

  Future<Map<String, dynamic>> uploadSpc(
    String deviceId,
    String filename,
    Uint8List bytes,
  ) async {
    final uri = _u('/spc/upload');
    try {
      final req = http.MultipartRequest('POST', uri)
        ..fields['device_id'] = deviceId
        ..files.add(
          http.MultipartFile.fromBytes(
            'spc_file',
            bytes,
            filename: filename.toLowerCase().endsWith('.spc')
                ? filename
                : '$filename.spc',
          ),
        );
      final streamed = await req.send().timeout(_timeout);
      final resp = await http.Response.fromStream(streamed);
      _ensureOk(resp);
      return _decode(resp);
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException('上传 SPC 文件失败: $e');
    }
  }

  // --------------------------------------------------------------------------
  // 辅助
  // --------------------------------------------------------------------------

  /// 将 [DateTime] 格式化为服务端接受的 "YYYY-MM-DD" 字符串。
  static String _fmtDate(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  Future<http.Response> _get(String path) async {
    final uri = _u(path);
    try {
      final resp = await http.get(uri).timeout(_timeout);
      _ensureOk(resp);
      return resp;
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException('请求 $path 失败: $e');
    }
  }

  Map<String, dynamic> _decode(http.Response resp) {
    try {
      final obj = jsonDecode(utf8.decode(resp.bodyBytes));
      if (obj is Map<String, dynamic>) return obj;
      throw ApiException('响应不是 JSON 对象: ${resp.body}');
    } on FormatException catch (e) {
      throw ApiException('响应解析失败: $e');
    }
  }

  void _ensureOk(http.Response resp) {
    if (resp.statusCode >= 200 && resp.statusCode < 300) return;
    String detail = resp.body;
    try {
      final obj = jsonDecode(utf8.decode(resp.bodyBytes));
      if (obj is Map && obj['detail'] != null) detail = obj['detail'].toString();
    } catch (_) {/* keep raw body */}
    throw ApiException('HTTP ${resp.statusCode}: $detail',
        statusCode: resp.statusCode);
  }
}

class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});
  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}
