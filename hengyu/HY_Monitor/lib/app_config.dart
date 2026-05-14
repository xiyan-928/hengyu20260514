/// 应用级常量：默认后端、默认轮询频率。
class AppConfig {
  /// 编译期可通过 `--dart-define=HY_BASE_URL=...` 注入；
  /// 未注入时回落到本机 test1.py 默认端口 8001。
  static const String defaultBaseUrl = String.fromEnvironment(
    'HY_BASE_URL',
    defaultValue: 'http://127.0.0.1:8001',
  );

  /// 设备列表刷新间隔（秒）
  static const int defaultDevicesRefreshSec = 5;

  /// 单设备实时快照刷新间隔（秒）
  static const int defaultDetailRefreshSec = 2;

  /// SPC 列表刷新间隔（秒）
  static const int defaultSpcRefreshSec = 10;

  /// HTTP 超时（秒）
  static const int httpTimeoutSec = 10;

  /// 历史曲线保留的最近点数上限（避免一次性渲染上万点卡顿）
  static const int maxHistoryPoints = 500;
}
