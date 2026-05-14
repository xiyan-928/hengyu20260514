class SensorConfig {
  final String driver;
  final bool enabled;
  final Map<String, dynamic> params;

  SensorConfig({
    required this.driver,
    this.enabled = true,
    this.params = const {},
  });

  factory SensorConfig.fromJson(Map<String, dynamic> json) {
    return SensorConfig(
      driver: json['driver'] as String? ?? 'Default',
      enabled: json['enabled'] as bool? ?? true,
      params: json['params'] as Map<String, dynamic>? ?? {},
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'driver': driver,
      'enabled': enabled,
      'params': params,
    };
  }
  
  SensorConfig copyWith({
    String? driver,
    bool? enabled,
    Map<String, dynamic>? params,
  }) {
    return SensorConfig(
      driver: driver ?? this.driver,
      enabled: enabled ?? this.enabled,
      params: params ?? this.params,
    );
  }
}

class RelayConfig {
  final int address;

  RelayConfig({required this.address});

  factory RelayConfig.fromJson(Map<String, dynamic> json) {
    return RelayConfig(
      address: json['address'] as int? ?? 0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'address': address,
    };
  }
}

class AutoControlConfig {
  final bool enabled;
  final String modbusHost;
  final int modbusPort;
  final int unitId;
  final int monitorRegister;
  final int waitTime; // in seconds
  final String scriptDefinePath;

  AutoControlConfig({
    this.enabled = false,
    this.modbusHost = 'localhost',
    this.modbusPort = 5020,
    this.unitId = 1,
    this.monitorRegister = 1,
    this.waitTime = 300,
    this.scriptDefinePath = 'define/script_define.xlsx',
  });

  factory AutoControlConfig.fromJson(Map<String, dynamic> json) {
    return AutoControlConfig(
      enabled: json['enabled'] as bool? ?? false,
      modbusHost: json['modbus_host'] as String? ?? 'localhost',
      modbusPort: json['modbus_port'] as int? ?? 5020,
      unitId: json['unit_id'] as int? ?? 1,
      monitorRegister: json['monitor_register'] as int? ?? 1,
      waitTime: json['wait_time'] as int? ?? 300,
      scriptDefinePath:
          json['script_define_path'] as String? ?? 'define/script_define.xlsx',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'enabled': enabled,
      'modbus_host': modbusHost,
      'modbus_port': modbusPort,
      'unit_id': unitId,
      'monitor_register': monitorRegister,
      'wait_time': waitTime,
      'script_define_path': scriptDefinePath,
    };
  }
  
  AutoControlConfig copyWith({
    bool? enabled,
    String? modbusHost,
    int? modbusPort,
    int? unitId,
    int? monitorRegister,
    int? waitTime,
    String? scriptDefinePath,
  }) {
    return AutoControlConfig(
      enabled: enabled ?? this.enabled,
      modbusHost: modbusHost ?? this.modbusHost,
      modbusPort: modbusPort ?? this.modbusPort,
      unitId: unitId ?? this.unitId,
      monitorRegister: monitorRegister ?? this.monitorRegister,
      waitTime: waitTime ?? this.waitTime,
      scriptDefinePath: scriptDefinePath ?? this.scriptDefinePath,
    );
  }
}

class AlarmConfig {
  final bool enabled;
  final int address;

  AlarmConfig({
    this.enabled = false,
    this.address = 10,
  });

  factory AlarmConfig.fromJson(Map<String, dynamic> json) {
    return AlarmConfig(
      enabled: json['enabled'] as bool? ?? false,
      address: json['address'] as int? ?? 10,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'enabled': enabled,
      'address': address,
    };
  }

  AlarmConfig copyWith({
    bool? enabled,
    int? address,
  }) {
    return AlarmConfig(
      enabled: enabled ?? this.enabled,
      address: address ?? this.address,
    );
  }
}

class FanConfig {
  final bool enabled;
  final int unit;
  final double targetTemp; // Deprecated but kept for compatibility
  final double startTemp;
  final double stopTemp;
  final int minSpeed;
  final int maxSpeed;
  final int kFactor;

  FanConfig({
    this.enabled = false,
    this.unit = 7,
    this.targetTemp = 25.0,
    this.startTemp = 30.0,
    this.stopTemp = 20.0,
    this.minSpeed = 50,
    this.maxSpeed = 100,
    this.kFactor = 5,
  });

  factory FanConfig.fromJson(Map<String, dynamic> json) {
    return FanConfig(
      enabled: json['enabled'] as bool? ?? false,
      unit: json['unit'] as int? ?? 7,
      targetTemp: (json['target_temp'] as num? ?? 25.0).toDouble(),
      startTemp: (json['start_temp'] as num? ?? 30.0).toDouble(),
      stopTemp: (json['stop_temp'] as num? ?? 20.0).toDouble(),
      minSpeed: json['min_speed'] as int? ?? 50,
      maxSpeed: json['max_speed'] as int? ?? 100,
      kFactor: json['k_factor'] as int? ?? 5,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'enabled': enabled,
      'unit': unit,
      'target_temp': targetTemp,
      'start_temp': startTemp,
      'stop_temp': stopTemp,
      'min_speed': minSpeed,
      'max_speed': maxSpeed,
      'k_factor': kFactor,
    };
  }

  FanConfig copyWith({
    bool? enabled,
    int? unit,
    double? targetTemp,
    double? startTemp,
    double? stopTemp,
    int? minSpeed,
    int? maxSpeed,
    int? kFactor,
  }) {
    return FanConfig(
      enabled: enabled ?? this.enabled,
      unit: unit ?? this.unit,
      targetTemp: targetTemp ?? this.targetTemp,
      startTemp: startTemp ?? this.startTemp,
      stopTemp: stopTemp ?? this.stopTemp,
      minSpeed: minSpeed ?? this.minSpeed,
      maxSpeed: maxSpeed ?? this.maxSpeed,
      kFactor: kFactor ?? this.kFactor,
    );
  }
}

/// 线圈网关 / 寄存器网关（与后端 `modbus_coils`、`modbus_holding` 对应）。
/// host、port 均为空时提交 `{}`，后端回退到主设备 `ip`/`port`。
class ModbusBusConfig {
  final String? host;
  final int? port;

  const ModbusBusConfig({this.host, this.port});

  factory ModbusBusConfig.fromJson(dynamic json) {
    if (json == null || json is! Map<String, dynamic>) {
      return const ModbusBusConfig();
    }
    final m = json;
    return ModbusBusConfig(
      host: m['host'] as String?,
      port: (m['port'] as num?)?.toInt(),
    );
  }

  Map<String, dynamic> toJson() {
    final out = <String, dynamic>{};
    if (host != null && host!.trim().isNotEmpty) {
      out['host'] = host!.trim();
    }
    if (port != null) {
      out['port'] = port;
    }
    return out;
  }

  ModbusBusConfig copyWith({String? host, int? port}) {
    return ModbusBusConfig(
      host: host ?? this.host,
      port: port ?? this.port,
    );
  }
}

class DeviceConfig {
  final String ip;
  final int port;
  final Map<String, SensorConfig> sensors;
  final Map<String, RelayConfig> relays;
  final ModbusBusConfig modbusCoils;
  final ModbusBusConfig modbusHolding;
  final AutoControlConfig autoControl;
  final AlarmConfig alarm;
  final FanConfig fan;

  DeviceConfig({
    required this.ip,
    required this.port,
    this.sensors = const {},
    this.relays = const {},
    ModbusBusConfig? modbusCoils,
    ModbusBusConfig? modbusHolding,
    AutoControlConfig? autoControl,
    AlarmConfig? alarm,
    FanConfig? fan,
  })  : modbusCoils = modbusCoils ?? const ModbusBusConfig(),
        modbusHolding = modbusHolding ?? const ModbusBusConfig(),
        autoControl = autoControl ?? AutoControlConfig(),
        alarm = alarm ?? AlarmConfig(),
        fan = fan ?? FanConfig();

  factory DeviceConfig.fromJson(Map<String, dynamic> json) {
    final sensorsJson = json['sensors'] as Map<String, dynamic>? ?? {};
    final sensors = sensorsJson.map(
      (key, value) => MapEntry(key, SensorConfig.fromJson(value)),
    );
    
    final relaysJson = json['relays'] as Map<String, dynamic>? ?? {};
    final relays = relaysJson.map(
      (key, value) => MapEntry(key, RelayConfig.fromJson(value)),
    );
    
    return DeviceConfig(
      ip: json['ip'] as String? ?? '192.168.1.12',
      port: json['port'] as int? ?? 502,
      sensors: sensors,
      relays: relays,
      modbusCoils: ModbusBusConfig.fromJson(json['modbus_coils']),
      modbusHolding: ModbusBusConfig.fromJson(json['modbus_holding']),
      autoControl: json['auto_control'] != null
          ? AutoControlConfig.fromJson(json['auto_control'])
          : AutoControlConfig(),
      alarm: json['alarm'] != null
          ? AlarmConfig.fromJson(json['alarm'])
          : AlarmConfig(),
      fan: json['fan'] != null
          ? FanConfig.fromJson(json['fan'])
          : FanConfig(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'ip': ip,
      'port': port,
      'sensors': sensors.map((key, value) => MapEntry(key, value.toJson())),
      'relays': relays.map((key, value) => MapEntry(key, value.toJson())),
      'modbus_coils': modbusCoils.toJson(),
      'modbus_holding': modbusHolding.toJson(),
      'auto_control': autoControl.toJson(),
      'alarm': alarm.toJson(),
      'fan': fan.toJson(),
    };
  }
  
  DeviceConfig copyWith({
    String? ip,
    int? port,
    Map<String, SensorConfig>? sensors,
    Map<String, RelayConfig>? relays,
    ModbusBusConfig? modbusCoils,
    ModbusBusConfig? modbusHolding,
    AutoControlConfig? autoControl,
    AlarmConfig? alarm,
    FanConfig? fan,
  }) {
    return DeviceConfig(
      ip: ip ?? this.ip,
      port: port ?? this.port,
      sensors: sensors ?? this.sensors,
      relays: relays ?? this.relays,
      modbusCoils: modbusCoils ?? this.modbusCoils,
      modbusHolding: modbusHolding ?? this.modbusHolding,
      autoControl: autoControl ?? this.autoControl,
      alarm: alarm ?? this.alarm,
      fan: fan ?? this.fan,
    );
  }
}

class CDS350Config {
  final int? integrationTime;
  final int? scansToAverage;

  CDS350Config({
    this.integrationTime,
    this.scansToAverage,
  });

  factory CDS350Config.fromJson(Map<String, dynamic> json) {
    return CDS350Config(
      integrationTime: json['integration_time'] as int?,
      scansToAverage: json['scans_to_average'] as int?,
    );
  }

  Map<String, dynamic> toJson() {
    final json = <String, dynamic>{};
    if (integrationTime != null) {
      json['integration_time'] = integrationTime;
    }
    if (scansToAverage != null) {
      json['scans_to_average'] = scansToAverage;
    }
    return json;
  }
}
