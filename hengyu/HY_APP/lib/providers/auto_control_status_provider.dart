import 'dart:async';
import 'package:flutter/foundation.dart';
import '../services/api_service.dart';

/// 全局唯一：每秒拉取一次 `/auto-control/status`，分发给光谱与传感器 Provider。
/// 避免 Spectrum/Sensor 各开一套 Timer 造成双倍请求与重叠 await。
class AutoControlStatusProvider extends ChangeNotifier {
  final ApiService _apiService = ApiService();
  Timer? _timer;
  bool _tickInFlight = false;
  bool _started = false;

  Future<void> Function(Map<String, dynamic> status)? spectrumHandler;
  Future<void> Function(Map<String, dynamic> status)? sensorHandler;

  void start() {
    if (_started) {
      return;
    }
    _started = true;
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    _started = false;
  }

  @override
  void dispose() {
    stop();
    super.dispose();
  }

  Future<void> _tick() async {
    if (_tickInFlight) {
      return;
    }
    _tickInFlight = true;
    try {
      final response = await _apiService.getAutoControlStatus();
      if (response.success && response.data != null) {
        final status = response.data!;
        if (spectrumHandler != null) {
          await spectrumHandler!(status);
        }
        if (sensorHandler != null) {
          await sensorHandler!(status);
        }
      }
    } catch (_) {
      // 与原先各 Provider 内行为一致：静默
    } finally {
      _tickInFlight = false;
    }
  }
}
