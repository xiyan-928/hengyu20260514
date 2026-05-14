import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/device_data.dart';
import '../services/api_service.dart';

/// 设备总览：设备 ID 列表 + 每台最新快照，定时轮询。
class DevicesProvider extends ChangeNotifier {
  DevicesProvider(this._api);

  ApiService _api;

  /// 更新后端基地址（来自 SettingsProvider），并触发一次刷新。
  void updateBaseUrl(String baseUrl) {
    if (_api.baseUrl == baseUrl) return;
    _api = ApiService(baseUrl);
    _latest.clear();
    _perDeviceError.clear();
    _deviceIds = const [];
    notifyListeners();
    refresh();
  }

  List<String> _deviceIds = const [];
  final Map<String, DeviceData> _latest = {};
  final Map<String, String> _perDeviceError = {};

  bool _loading = false;
  String? _error;
  DateTime? _lastRefreshAt;
  bool _online = false;

  Timer? _timer;
  Duration _interval = const Duration(seconds: 5);

  List<String> get deviceIds => List.unmodifiable(_deviceIds);
  Map<String, DeviceData> get latestByDevice => Map.unmodifiable(_latest);
  bool get loading => _loading;
  String? get error => _error;
  bool get isOnline => _online;
  DateTime? get lastRefreshAt => _lastRefreshAt;
  String? errorFor(String deviceId) => _perDeviceError[deviceId];

  void start({Duration? interval}) {
    if (interval != null) _interval = interval;
    _timer?.cancel();
    _timer = Timer.periodic(_interval, (_) => refresh());
    refresh();
  }

  void updateInterval(Duration interval) {
    if (interval == _interval) return;
    _interval = interval;
    if (_timer != null) start(interval: interval);
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  Future<void> refresh() async {
    if (_loading) return;
    _loading = true;
    notifyListeners();

    try {
      final ids = await _api.listDevices();
      _deviceIds = ids;
      _error = null;
      _online = true;

      // 并行拉各自最新快照
      await Future.wait(ids.map(_fetchLatest));
      _lastRefreshAt = DateTime.now();
    } catch (e) {
      _error = e.toString();
      _online = false;
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> _fetchLatest(String deviceId) async {
    try {
      final d = await _api.getLatest(deviceId);
      _latest[deviceId] = d;
      _perDeviceError.remove(deviceId);
    } catch (e) {
      _perDeviceError[deviceId] = e.toString();
    }
  }

  @override
  void dispose() {
    stop();
    super.dispose();
  }
}
