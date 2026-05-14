/// 设备重置相关的模型类

/// 设备重置请求模型
class DeviceResetRequest {
  final String ip;
  final int port;
  final int register;
  final bool mockMode;

  const DeviceResetRequest({
    required this.ip,
    required this.port,
    required this.register,
    required this.mockMode,
  });

  Map<String, dynamic> toJson() {
    return {
      'ip': ip,
      'port': port,
      'register': register,
      'mock_mode': mockMode,
    };
  }
}

/// 设备重置响应模型
class DeviceResetResponse {
  final String taskId;
  final String ip;
  final int port;
  final int register;
  final bool mockMode;
  final String estimatedDuration;
  final String status;

  const DeviceResetResponse({
    required this.taskId,
    required this.ip,
    required this.port,
    required this.register,
    required this.mockMode,
    required this.estimatedDuration,
    required this.status,
  });

  factory DeviceResetResponse.fromJson(Map<String, dynamic> json) {
    return DeviceResetResponse(
      taskId: json['task_id'] ?? '',
      ip: json['ip'] ?? '',
      port: json['port'] ?? 502,
      register: json['register'] ?? 0,
      mockMode: json['mock_mode'] ?? false,
      estimatedDuration: json['estimated_duration'] ?? '',
      status: json['status'] ?? '',
    );
  }
}

/// 设备重置状态查询响应模型
class DeviceResetStatus {
  final String taskId;
  final String status;
  final double durationSeconds;
  final Map<String, dynamic>? result;
  final String? error;
  final double? estimatedRemaining;
  final double? estimatedTotal;

  const DeviceResetStatus({
    required this.taskId,
    required this.status,
    required this.durationSeconds,
    this.result,
    this.error,
    this.estimatedRemaining,
    this.estimatedTotal,
  });

  factory DeviceResetStatus.fromJson(Map<String, dynamic> json) {
    return DeviceResetStatus(
      taskId: json['task_id'] ?? '',
      status: json['status'] ?? '',
      durationSeconds: (json['duration_seconds'] ?? 0).toDouble(),
      result: json['result'] as Map<String, dynamic>?,
      error: json['error'] as String?,
      estimatedRemaining: (json['estimated_remaining'] ?? 0).toDouble(),
      estimatedTotal: (json['estimated_total'] ?? 0).toDouble(),
    );
  }

  /// 是否正在运行
  bool get isRunning => status == 'running';
  
  /// 是否已完成
  bool get isCompleted => status == 'completed';
  
  /// 是否失败
  bool get isFailed => status == 'failed';
  
  /// 获取进度百分比 (0.0 - 1.0)
  double get progress {
    if (estimatedTotal == null || estimatedTotal! <= 0) return 0.0;
    final elapsed = durationSeconds;
    return (elapsed / estimatedTotal!).clamp(0.0, 1.0);
  }
}

/// 设备模式信息模型
class DeviceMode {
  final String mode;
  final String description;
  final bool isMock;

  const DeviceMode({
    required this.mode,
    required this.description,
    required this.isMock,
  });

  factory DeviceMode.fromJson(Map<String, dynamic> json) {
    return DeviceMode(
      mode: json['mode'] ?? '',
      description: json['description'] ?? '',
      isMock: json['is_mock'] ?? false,
    );
  }
}
