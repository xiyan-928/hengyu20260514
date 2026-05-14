/// 与 `HY_Online/edge_device_data.py::DeviceData` 字段对齐。
///
/// 后端 `extra='ignore'`，允许部分字段缺失；前端同样使用安全的默认值解析，
/// 以便边缘端 schema 微调时 App 不会崩溃。
class DeviceData {
  DeviceData({
    required this.deviceId,
    this.ddl = 0.0,
    this.ph = 0.0,
    this.phTemp = 0.0,
    this.pt100 = 0.0,
    this.valves = const <String, bool>{},
    this.isAlarming = false,
    this.fanSpeed = 0,
    this.fanReadOk = false,
    this.fanLastError,
    this.fanLastReadTs,
    this.lastUpdateTs,
    this.lastError,
    this.running = true,
    this.interval = 2.0,
    this.serverTime,
    // ---- BridgeDataManager 字段（来自 hy_server.py） ----
    this.temperature = 0.0,
    this.level = 0.0,
    this.bridgeState = 'reset',
    this.bridgeError,
    this.bridgeLastUpdateTs,
    // ---- 工艺/批次元数据（可选，历史页侧栏展示） ----
    this.generationBatch,
    this.fabricWeightG,
    this.fabricLength,
    this.fabricWidth,
    this.fabricHeight,
    this.fabricThickness,
    this.fabricDensity,
    this.fabricMaterial,
    this.bathRatio,
  });

  final String deviceId;
  final double ddl;
  final double ph;
  final double phTemp;
  final double pt100;
  final Map<String, bool> valves;
  final bool isAlarming;
  final int fanSpeed;
  final bool fanReadOk;
  final String? fanLastError;
  final double? fanLastReadTs;
  final double? lastUpdateTs;
  final String? lastError;
  final bool running;
  final double interval;

  /// test1.py 会在 `/upload` 时注入 `server_time`（字符串，格式 YYYY-MM-DD HH:MM:SS）。
  final String? serverTime;

  // ---- BridgeDataManager 字段（来自 hy_server.py） ----
  /// 温度传感器读数（°C）
  final double temperature;

  /// 液位传感器读数
  final double level;

  /// 桥接状态："reset"（待机）或 "triggered"（已触发）
  final String bridgeState;

  /// 最近一次桥接读取异常信息，正常时为 null
  final String? bridgeError;

  /// 桥接数据最后更新的 Unix 时间戳（秒）
  final double? bridgeLastUpdateTs;

  /// 生成批次
  final String? generationBatch;

  /// 布重（g）
  final double? fabricWeightG;

  /// 布 — 长
  final double? fabricLength;

  /// 布 — 宽
  final double? fabricWidth;

  /// 布 — 高
  final double? fabricHeight;

  /// 布 — 厚
  final double? fabricThickness;

  /// 布 — 密度
  final double? fabricDensity;

  /// 布 — 材料
  final String? fabricMaterial;

  /// 浴比
  final double? bathRatio;

  factory DeviceData.fromJson(Map<String, dynamic> json) {
    return DeviceData(
      deviceId: (json['device_id'] ?? '').toString(),
      ddl: _toDouble(json['ddl']),
      ph: _toDouble(json['ph']),
      phTemp: _toDouble(json['ph_temp']),
      pt100: _toDouble(json['pt100']),
      valves: _toValves(json['valves']),
      isAlarming: json['is_alarming'] == true,
      fanSpeed: _toInt(json['fan_speed']),
      fanReadOk: json['fan_read_ok'] == true,
      fanLastError: json['fan_last_error']?.toString(),
      fanLastReadTs: _toDoubleOrNull(json['fan_last_read_ts']),
      lastUpdateTs: _toDoubleOrNull(json['last_update_ts']),
      lastError: json['last_error']?.toString(),
      running: json['running'] != false,
      interval: _toDouble(json['interval'], fallback: 2.0),
      serverTime: json['server_time']?.toString(),
      temperature: _toDouble(json['temperature']),
      level: _toDouble(json['level']),
      bridgeState: (json['bridge_state'] ?? 'reset').toString(),
      bridgeError: json['bridge_error']?.toString(),
      bridgeLastUpdateTs: _toDoubleOrNull(json['bridge_last_update_ts']),
      generationBatch: _toOptionalString(json['generation_batch']),
      fabricWeightG: _toDoubleOrNull(json['fabric_weight_g']),
      fabricLength: _toDoubleOrNull(json['fabric_length']),
      fabricWidth: _toDoubleOrNull(json['fabric_width']),
      fabricHeight: _toDoubleOrNull(json['fabric_height']),
      fabricThickness: _toDoubleOrNull(json['fabric_thickness']),
      fabricDensity: _toDoubleOrNull(json['fabric_density']),
      fabricMaterial: _toOptionalString(json['fabric_material']),
      bathRatio: _toDoubleOrNull(json['bath_ratio']),
    );
  }

  Map<String, dynamic> toUploadJson() => <String, dynamic>{
        'device_id': deviceId,
        'ddl': ddl,
        'ph': ph,
        'ph_temp': phTemp,
        'pt100': pt100,
        'valves': valves,
        'is_alarming': isAlarming,
        'fan_speed': fanSpeed,
        'fan_read_ok': fanReadOk,
        if (fanLastError != null) 'fan_last_error': fanLastError,
        if (fanLastReadTs != null) 'fan_last_read_ts': fanLastReadTs,
        if (lastUpdateTs != null) 'last_update_ts': lastUpdateTs,
        if (lastError != null) 'last_error': lastError,
        'running': running,
        'interval': interval,
        if (generationBatch != null) 'generation_batch': generationBatch,
        if (fabricWeightG != null) 'fabric_weight_g': fabricWeightG,
        if (fabricLength != null) 'fabric_length': fabricLength,
        if (fabricWidth != null) 'fabric_width': fabricWidth,
        if (fabricHeight != null) 'fabric_height': fabricHeight,
        if (fabricThickness != null) 'fabric_thickness': fabricThickness,
        if (fabricDensity != null) 'fabric_density': fabricDensity,
        if (fabricMaterial != null) 'fabric_material': fabricMaterial,
        if (bathRatio != null) 'bath_ratio': bathRatio,
      };

  /// 尝试从 server_time(字符串) 或 last_update_ts(unix 秒) 拿到可比时刻。
  DateTime? get timestamp {
    if (serverTime != null && serverTime!.isNotEmpty) {
      try {
        return DateTime.parse(serverTime!.replaceFirst(' ', 'T'));
      } catch (_) {/* fallthrough */}
    }
    if (lastUpdateTs != null) {
      return DateTime.fromMillisecondsSinceEpoch(
        (lastUpdateTs! * 1000).round(),
      );
    }
    return null;
  }

  static double _toDouble(dynamic v, {double fallback = 0.0}) {
    if (v is num) return v.toDouble();
    if (v is String) return double.tryParse(v) ?? fallback;
    return fallback;
  }

  static double? _toDoubleOrNull(dynamic v) {
    if (v == null) return null;
    if (v is num) return v.toDouble();
    if (v is String) return double.tryParse(v);
    return null;
  }

  static int _toInt(dynamic v, {int fallback = 0}) {
    if (v is int) return v;
    if (v is num) return v.toInt();
    if (v is String) return int.tryParse(v) ?? fallback;
    return fallback;
  }

  static Map<String, bool> _toValves(dynamic v) {
    if (v is Map) {
      return v.map((key, value) => MapEntry(key.toString(), value == true));
    }
    return const <String, bool>{};
  }

  static String? _toOptionalString(dynamic v) {
    if (v == null) return null;
    final s = v.toString();
    return s.isEmpty ? null : s;
  }
}
