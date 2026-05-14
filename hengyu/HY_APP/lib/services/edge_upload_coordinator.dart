import '../utils/app_config.dart';
import 'api_service.dart';

enum EdgeUploadChannel { sensor, spc }

/// 与主服务 upload-relay 联动，按通道分别控制传感器 / 光谱上传开关。
class EdgeUploadCoordinator {
  static int _sensorRef = 0;
  static int _spcRef = 0;

  static Future<void> acquire(ApiService api, EdgeUploadChannel channel) async {
    if (!AppConfig.linkUploadRelayToCollection) return;

    final nextValue = _getRef(channel) + 1;
    _setRef(channel, nextValue);

    if (nextValue == 1) {
      final r = await _setChannelState(api, channel, true);
      if (!r.success) {
        _setRef(channel, nextValue - 1);
        // ignore: avoid_print
        print('upload-relay: ${channel.name} start 失败 ${r.message}，已回滚引用');
      }
    }
  }

  static Future<void> release(ApiService api, EdgeUploadChannel channel) async {
    if (!AppConfig.linkUploadRelayToCollection) return;
    final currentValue = _getRef(channel);
    if (currentValue <= 0) return;

    final nextValue = currentValue - 1;
    _setRef(channel, nextValue);

    if (nextValue == 0) {
      await _setChannelState(api, channel, false);
    }
  }

  static int _getRef(EdgeUploadChannel channel) {
    switch (channel) {
      case EdgeUploadChannel.sensor:
        return _sensorRef;
      case EdgeUploadChannel.spc:
        return _spcRef;
    }
  }

  static void _setRef(EdgeUploadChannel channel, int value) {
    switch (channel) {
      case EdgeUploadChannel.sensor:
        _sensorRef = value;
        break;
      case EdgeUploadChannel.spc:
        _spcRef = value;
        break;
    }
  }

  static Future<dynamic> _setChannelState(
    ApiService api,
    EdgeUploadChannel channel,
    bool enabled,
  ) {
    switch (channel) {
      case EdgeUploadChannel.sensor:
        return api.setUploadRelay(uploadSensor: enabled);
      case EdgeUploadChannel.spc:
        return api.setUploadRelay(uploadSpc: enabled);
    }
  }
}
