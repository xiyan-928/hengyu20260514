import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../app_config.dart';

/// 持久化 base_url / 刷新间隔等用户可调项。
class SettingsProvider extends ChangeNotifier {
  SettingsProvider();

  static const _kBaseUrl = 'base_url';
  static const _kDevicesRefreshSec = 'devices_refresh_sec';
  static const _kDetailRefreshSec = 'detail_refresh_sec';

  String _baseUrl = AppConfig.defaultBaseUrl;
  int _devicesRefreshSec = AppConfig.defaultDevicesRefreshSec;
  int _detailRefreshSec = AppConfig.defaultDetailRefreshSec;
  bool _loaded = false;

  String get baseUrl => _baseUrl;
  int get devicesRefreshSec => _devicesRefreshSec;
  int get detailRefreshSec => _detailRefreshSec;
  bool get isLoaded => _loaded;

  Future<void> load() async {
    final sp = await SharedPreferences.getInstance();
    _baseUrl = sp.getString(_kBaseUrl) ?? AppConfig.defaultBaseUrl;
    _devicesRefreshSec =
        sp.getInt(_kDevicesRefreshSec) ?? AppConfig.defaultDevicesRefreshSec;
    _detailRefreshSec =
        sp.getInt(_kDetailRefreshSec) ?? AppConfig.defaultDetailRefreshSec;
    _loaded = true;
    notifyListeners();
  }

  Future<void> updateBaseUrl(String value) async {
    final v = value.trim();
    if (v.isEmpty || v == _baseUrl) return;
    _baseUrl = v;
    final sp = await SharedPreferences.getInstance();
    await sp.setString(_kBaseUrl, v);
    notifyListeners();
  }

  Future<void> updateDevicesRefreshSec(int value) async {
    if (value <= 0 || value == _devicesRefreshSec) return;
    _devicesRefreshSec = value;
    final sp = await SharedPreferences.getInstance();
    await sp.setInt(_kDevicesRefreshSec, value);
    notifyListeners();
  }

  Future<void> updateDetailRefreshSec(int value) async {
    if (value <= 0 || value == _detailRefreshSec) return;
    _detailRefreshSec = value;
    final sp = await SharedPreferences.getInstance();
    await sp.setInt(_kDetailRefreshSec, value);
    notifyListeners();
  }
}
