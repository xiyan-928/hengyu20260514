import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/spectrum_provider.dart';
import '../providers/sensor_provider.dart';
import '../providers/valve_control_provider.dart';
import '../services/api_service.dart';
import '../widgets/spectrum_chart.dart';
import '../widgets/sensor_data_widget.dart';
import 'settings_screen.dart';
import 'hardware_control_screen.dart';
import 'device_config_screen.dart';

class AppLayoutScreen extends StatefulWidget {
  const AppLayoutScreen({super.key});

  @override
  State<AppLayoutScreen> createState() => _AppLayoutScreenState();
}

class _AppLayoutScreenState extends State<AppLayoutScreen> {
  int _selectedIndex = 0;
  bool _isInitialized = false;

  final List<NavigationItem> _navigationItems = [
    NavigationItem(
      icon: Icons.timeline,
      label: '在线采集',
      title: '优谱德在线数据采集系统',
    ),
    NavigationItem(
      icon: Icons.settings,
      label: '设置',
      title: '设置',
    ),
    NavigationItem(
      icon: Icons.settings_ethernet,
      label: '设备配置',
      title: '设备配置',
    ),
    NavigationItem(
      icon: Icons.hardware,
      label: '硬件控制',
      title: '硬件控制',
    ),
  ];

  @override
  void initState() {
    super.initState();
    _initializeApp();
  }

  Future<void> _initializeApp() async {
    final spectrumProvider = Provider.of<SpectrumProvider>(context, listen: false);
    final sensorProvider = Provider.of<SensorProvider>(context, listen: false);
    final valveProvider = Provider.of<ValveControlProvider>(context, listen: false);

    // Load user settings first
    await spectrumProvider.initialize();

    // Initialize CDS350
    await spectrumProvider.initializeDevice();

    // Fetch device settings from backend to get correct IP/Port
    final apiService = ApiService();
    late final String deviceIp;
    late final int devicePort;

    try {
      final settingsResponse = await apiService.getDeviceSettings();
      if (settingsResponse.success && settingsResponse.data != null) {
        deviceIp = settingsResponse.data!.ip;
        devicePort = settingsResponse.data!.port;
        debugPrint('Fetched device config: $deviceIp:$devicePort');
      } else {
        throw Exception('获取设备配置失败: ${settingsResponse.message}');
      }

      await _ensureWarmupDialog(apiService);
    } catch (e) {
      debugPrint('Error fetching device settings: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('错误: 无法获取服务器配置，请检查连接 ($e)'),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 5),
          ),
        );
      }
      // Stop initialization if we can't get the config
      // We don't want to use a hardcoded fallback that might modify the backend
      setState(() {
        _isInitialized = true; // Still set initialized to show UI, but sensors won't be connected
      });
      return;
    }

    // Initialize sensors with fetched settings
    await sensorProvider.initializeSensors(deviceIp, devicePort);

    // Initialize valve control
    await valveProvider.initialize();

    setState(() {
      _isInitialized = true;
    });
  }

  /// 若服务器尚未完成开机预热，询问是否通水冲洗并同步标志位。
  Future<void> _ensureWarmupDialog(ApiService api) async {
    final statusResp = await api.getAutoControlStatus();
    if (!statusResp.success || statusResp.data == null) {
      return;
    }
    final hasWarmup = statusResp.data!['has_warmup'];
    if (hasWarmup == true) {
      return;
    }
    if (!mounted) {
      return;
    }
    final withWater = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        title: const Text('开机预热'),
        content: const Text('是否用水冲洗？\n选择「是」将执行通水预热脚本；选择「否」将跳过并标记为已预热。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('否'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('是'),
          ),
        ],
      ),
    );
    if (!mounted || withWater == null) {
      return;
    }
    final post = await api.postWarmupChoice(withWater: withWater);
    if (!post.success && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('预热选择提交失败: ${post.message}'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }
    if (withWater && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('预热进行中，请稍候…')),
      );
      for (var i = 0; i < 600; i++) {
        await Future<void>.delayed(const Duration(seconds: 1));
        final s2 = await api.getAutoControlStatus();
        if (s2.success && s2.data?['has_warmup'] == true) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('预热已完成')),
            );
          }
          break;
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        children: [
          _buildSideNavigation(),
          Expanded(
            child: _isInitialized ? _buildMainContent() : _buildLoadingScreen(),
          ),
        ],
      ),
    );
  }

  Widget _buildSideNavigation() {
    return Container(
      width: 200,
      decoration: BoxDecoration(
        color: Colors.blue.shade700,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.1),
            blurRadius: 4,
            offset: const Offset(2, 0),
          ),
        ],
      ),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            child: const Column(
              children: [
                Icon(
                  Icons.analytics,
                  color: Colors.white,
                  size: 40,
                ),
                SizedBox(height: 8),
                Text(
                  'HY 采集系统',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: _navigationItems.length,
              itemBuilder: (context, index) {
                final item = _navigationItems[index];
                final isSelected = index == _selectedIndex;
                return Container(
                  margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  child: Material(
                    color: isSelected ? Colors.white.withOpacity(0.2) : Colors.transparent,
                    borderRadius: BorderRadius.circular(8),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(8),
                      onTap: () {
                        setState(() {
                          _selectedIndex = index;
                        });
                      },
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                        child: Row(
                          children: [
                            Icon(
                              item.icon,
                              color: Colors.white,
                              size: 20,
                            ),
                            const SizedBox(width: 12),
                            Text(
                              item.label,
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 14,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLoadingScreen() {
    return const Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          CircularProgressIndicator(),
          SizedBox(height: 16),
          Text(
            '设备初始化中...',
            style: TextStyle(
              fontSize: 16,
              color: Colors.black87,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMainContent() {
    switch (_selectedIndex) {
      case 0:
        return const DataCollectionContent();
      case 1:
        return const SettingsScreen();
      case 2:
        return const DeviceConfigScreen();
      case 3:
        return const HardwareControlScreen();
      default:
        return const DataCollectionContent();
    }
  }
}

class NavigationItem {
  final IconData icon;
  final String label;
  final String title;

  NavigationItem({
    required this.icon,
    required this.label,
    required this.title,
  });
}

class DataCollectionContent extends StatefulWidget {
  const DataCollectionContent({super.key});

  @override
  State<DataCollectionContent> createState() => _DataCollectionContentState();
}

class _DataCollectionContentState extends State<DataCollectionContent> {
  // 与后端字段保持一致的占位常量；未拿到任何来源单号时显示该值。
  static const String _orderPlaceholder = '未获取';

  String _serverOrderNumber = '';
  String _manualOrderNumber = '';
  /// 后端 ``effective``；展示以 ``source``+分字段为准，本字段作兜底。
  String _effectiveOrderNumber = '';
  String _orderSource = 'placeholder'; // server / manual / placeholder
  Timer? _orderPollTimer;
  final ApiService _orderApi = ApiService();

  static String _orderStrFromPayload(dynamic v) {
    if (v == null) return '';
    final s = v.toString().trim();
    return s;
  }

  @override
  void initState() {
    super.initState();
    _refreshOrderNumber();
    // 后端轮询 server 单号；前端定期同步 UI
    _orderPollTimer = Timer.periodic(
      const Duration(seconds: 3),
      (_) => _refreshOrderNumber(),
    );
  }

  @override
  void dispose() {
    _orderPollTimer?.cancel();
    _orderApi.dispose();
    super.dispose();
  }

  Future<void> _refreshOrderNumber() async {
    final resp = await _orderApi.getOrderNumberState();
    if (!mounted || !resp.success || resp.data == null) return;
    final data = resp.data!;
    setState(() {
      _serverOrderNumber = _orderStrFromPayload(data['server_value']);
      _manualOrderNumber = _orderStrFromPayload(data['manual_value']);
      _effectiveOrderNumber = _orderStrFromPayload(data['effective']);
      final src = _orderStrFromPayload(data['source']).toLowerCase();
      _orderSource = src.isEmpty ? 'placeholder' : src;
    });
  }

  String get _displayedOrderNumber {
    // 与「服务器 > 手动」及角标 source 对齐：优先用对应来源字段，避免 effective 滞后或 JSON 类型不一致
    switch (_orderSource) {
      case 'server':
        if (_serverOrderNumber.isNotEmpty) return _serverOrderNumber;
        break;
      case 'manual':
        if (_manualOrderNumber.isNotEmpty) return _manualOrderNumber;
        break;
    }
    final e = _effectiveOrderNumber.trim();
    if (e.isNotEmpty && e != _orderPlaceholder) return e;
    if (_serverOrderNumber.isNotEmpty) return _serverOrderNumber;
    if (_manualOrderNumber.isNotEmpty) return _manualOrderNumber;
    return _orderPlaceholder;
  }

  /// 输入框旁说明：与后端「服务器覆盖手改」一致。
  Widget _orderDialogHint() {
    final lines = <String>[];
    if (_serverOrderNumber.isNotEmpty) {
      lines.add('当前由服务器下发：$_serverOrderNumber');
      lines.add('有新下发时会覆盖手改；仅当服务器暂无单号时，手动输入才会作为主界面单号。');
    } else if (_manualOrderNumber.isNotEmpty) {
      lines.add('当前为手动单号（服务器暂无下发）。服务器一旦下发将自动切换为服务器单号。');
    }
    if (lines.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Text(
        lines.join('\n'),
        style: TextStyle(
          fontSize: 12,
          color: Colors.orange.shade800,
        ),
      ),
    );
  }

  String get _orderSourceLabel {
    switch (_orderSource) {
      case 'server':
        return '服务器下发';
      case 'manual':
        return '手动输入';
      default:
        return '占位';
    }
  }

  void _showOrderNumberDialog() {
    final dialogController =
        TextEditingController(text: _manualOrderNumber);
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.tag, color: Colors.blue),
            SizedBox(width: 8),
            Text('输入单号'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _orderDialogHint(),
            TextField(
              controller: dialogController,
              autofocus: true,
              decoration: const InputDecoration(
                hintText: '请输入单号（留空清除手动值）',
                border: OutlineInputBorder(),
              ),
              onSubmitted: (_) => _confirmOrderNumber(ctx, dialogController),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('取消'),
          ),
          ElevatedButton(
            onPressed: () => _confirmOrderNumber(ctx, dialogController),
            child: const Text('确认'),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmOrderNumber(
      BuildContext ctx, TextEditingController controller) async {
    final value = controller.text.trim();
    Navigator.of(ctx).pop();
    final resp = await _orderApi.setManualOrderNumber(
      value.isEmpty ? null : value,
    );
    if (!mounted) return;
    if (!resp.success) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('单号提交失败：${resp.message}'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }
    await _refreshOrderNumber();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey.shade50,
      appBar: AppBar(
        title: const Text(
          '在线数据采集',
          style: TextStyle(
            fontWeight: FontWeight.w600,
            color: Colors.white,
          ),
        ),
        backgroundColor: Colors.blue.shade700,
        elevation: 0,
        automaticallyImplyLeading: false,
        actions: [
          Center(
            child: GestureDetector(
              onTap: _showOrderNumberDialog,
              child: Container(
                margin: const EdgeInsets.only(right: 12),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.18),
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: Colors.white.withOpacity(0.35)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text(
                      '单号：',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 13,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      _displayedOrderNumber,
                      style: TextStyle(
                        color: _orderSource == 'placeholder'
                            ? Colors.white.withOpacity(0.7)
                            : Colors.white,
                        fontSize: 15,
                        fontWeight: _orderSource == 'placeholder'
                            ? FontWeight.w400
                            : FontWeight.w600,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: Colors.white.withOpacity(0.25),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        _orderSourceLabel,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 10,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            _buildControlPanel(),
            const SizedBox(height: 16),
            _buildSpectrumSection(),
            const SizedBox(height: 16),
            _buildSensorSection(),
          ],
        ),
      ),
    );
  }

  Widget _buildControlPanel() {
    return Consumer2<SpectrumProvider, SensorProvider>(
      builder: (context, spectrumProvider, sensorProvider, child) {
        return Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.grey.shade300),
          ),
          child: Column(
            children: [
              Row(
                children: [
                  const Icon(Icons.control_camera, color: Colors.blue),
                  const SizedBox(width: 8),
                  const Text(
                    '控制面板',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const Spacer(),
                  _buildStatusIndicator(spectrumProvider, sensorProvider),
                ],
              ),
              const SizedBox(height: 16),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: _buildSpectrumControls(context, spectrumProvider),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: _buildSensorControls(context, sensorProvider),
                  ),
                ],
              ),
              
              if (sensorProvider.isAlarming) ...[
                const SizedBox(height: 16),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.red.shade50,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.red.shade300),
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.warning, color: Colors.red.shade700),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '系统报警触发',
                              style: TextStyle(
                                color: Colors.red.shade900,
                                fontWeight: FontWeight.bold,
                                fontSize: 16,
                              ),
                            ),
                            Text(
                              '已强制关闭所有阀门',
                              style: TextStyle(
                                color: Colors.red.shade700,
                                fontSize: 14,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              
            ],
          ),
        );
      },
    );
  }

  Widget _buildStatusIndicator(SpectrumProvider spectrumProvider, SensorProvider sensorProvider) {
    final spectrumStatus = spectrumProvider.isInitialized;
    final sensorStatus = sensorProvider.isConnected;
    final bridgeStatus = sensorProvider.bridgeConnected;
    final bridgeTip = _bridgeTooltip(sensorProvider);

    return Row(
      children: [
        _buildStatusDot('光谱仪', spectrumStatus),
        const SizedBox(width: 12),
        _buildStatusDot('传感器', sensorStatus),
        const SizedBox(width: 12),
        _buildStatusDot(
          '桥接',
          bridgeStatus,
          icon: Icons.cable,
          tooltip: bridgeTip,
        ),
      ],
    );
  }

  String _bridgeTooltip(SensorProvider sensorProvider) {
    if (sensorProvider.bridgeError != null && sensorProvider.bridgeError!.isNotEmpty) {
      return '桥接异常: ${sensorProvider.bridgeError}';
    }
    final ts = sensorProvider.bridgeLastUpdateTs;
    if (ts == null) return '桥接尚未收到数据';
    return '桥接 ${sensorProvider.bridgeConnected ? "正常" : "数据陈旧"}\n最近更新: ${ts.toLocal()}';
  }

  Widget _buildStatusDot(
    String label,
    bool isConnected, {
    IconData? icon,
    String? tooltip,
  }) {
    final color = isConnected ? Colors.green : Colors.red;
    final dot = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (icon != null) ...[
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 4),
        ] else ...[
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 4),
        ],
        Text(
          label,
          style: TextStyle(
            fontSize: 12,
            color: Colors.grey.shade700,
          ),
        ),
      ],
    );
    if (tooltip == null || tooltip.isEmpty) return dot;
    return Tooltip(message: tooltip, child: dot);
  }

  Widget _buildSpectrumControls(BuildContext context, SpectrumProvider provider) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '光谱采集',
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w500,
          ),
        ),
        const SizedBox(height: 8),
        if (provider.isAutoControlMode)
          Container(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
            decoration: BoxDecoration(
              color: Colors.blue.shade50,
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: Colors.blue.shade200),
            ),
            child: Row(
              children: [
                SizedBox(
                  width: 12,
                  height: 12,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.blue.shade700),
                ),
                const SizedBox(width: 8),
                Text(
                  '自动控制模式运行中...',
                  style: TextStyle(
                    fontSize: 12,
                    color: Colors.blue.shade700,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
          )
        else
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: provider.isCollecting
                      ? () => provider.stopCollection()
                      : () async => await provider.startCollection(),
                  icon: Icon(
                    provider.isCollecting ? Icons.stop : Icons.play_arrow,
                    size: 16,
                  ),
                  label: Text(
                    provider.isCollecting ? '停止' : '开始',
                    style: const TextStyle(fontSize: 12),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: provider.isCollecting ? Colors.red : Colors.green,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 8),
                  ),
                ),
              ),
            ],
          ),
      ],
    );
  }



  Widget _buildSensorControls(BuildContext context, SensorProvider provider) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '传感器采集',
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w500,
          ),
        ),
        const SizedBox(height: 8),
        if (provider.isAutoControlMode)
           Container(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
            decoration: BoxDecoration(
              color: Colors.blue.shade50,
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: Colors.blue.shade200),
            ),
            child: Row(
              children: [
                SizedBox(
                  width: 12,
                  height: 12,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.blue.shade700),
                ),
                const SizedBox(width: 8),
                Text(
                  '自动控制模式运行中...',
                  style: TextStyle(
                    fontSize: 12,
                    color: Colors.blue.shade700,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
          )
        else
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: provider.isCollecting
                      ? () => provider.stopCollection()
                      : () => provider.startCollection(),
                  icon: Icon(
                    provider.isCollecting ? Icons.stop : Icons.play_arrow,
                    size: 16,
                  ),
                  label: Text(
                    provider.isCollecting ? '停止' : '开始',
                    style: const TextStyle(fontSize: 12),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: provider.isCollecting ? Colors.red : Colors.purple,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 8),
                  ),
                ),
              ),
            ],
          ),
        const SizedBox(height: 4),
        Text(
          provider.status,
          style: TextStyle(
            fontSize: 10,
            color: Colors.grey.shade600,
          ),
        ),
        const SizedBox(height: 8),
        // Always show fan speed
        Row(
          children: [
            Icon(Icons.cyclone, size: 14, color: Colors.blue.shade600),
            const SizedBox(width: 4),
            Text(
              '风扇转速: ${provider.fanSpeed}',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w500,
                color: Colors.blue.shade700,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildSpectrumSection() {
    return Consumer<SpectrumProvider>(
      builder: (context, provider, child) {
        return Container(
          height: 400,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.grey.shade300),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.show_chart, color: Colors.blue),
                  const SizedBox(width: 8),
                  const Text(
                    '光谱数据',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              Expanded(
                child: provider.currentSpectrum != null
                    ? SpectrumChart(spectrumData: provider.currentSpectrum!)
                    : const Center(
                        child: Text(
                          '暂无光谱数据',
                          style: TextStyle(fontSize: 16, color: Colors.grey),
                        ),
                      ),
              ),
            ],
          ),
        );
      },
    );
  }



  Widget _buildSensorSection() {
    return Consumer<SensorProvider>(
      builder: (context, provider, child) {
        return SensorDataWidget(
          sensorData: provider.currentSensorData,
          historicalData: provider.historicalSensorData,
          isCollecting: provider.isCollecting,
          status: provider.status,
          bridgeTemperature: provider.bridgeTemperature,
          bridgeLevel: provider.bridgeLevel,
          bridgeState: provider.bridgeState,
          bridgeError: provider.bridgeError,
          bridgeLastUpdateTs: provider.bridgeLastUpdateTs,
          bridgeConnected: provider.bridgeConnected,
          bridgeAvailable: provider.bridgeApiAvailable,
        );
      },
    );
  }
}
