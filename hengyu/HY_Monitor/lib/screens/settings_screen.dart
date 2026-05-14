import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/device_data.dart';
import '../providers/devices_provider.dart';
import '../providers/settings_provider.dart';
import '../services/api_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late TextEditingController _urlCtrl;
  late TextEditingController _devRefreshCtrl;
  late TextEditingController _detailRefreshCtrl;

  @override
  void initState() {
    super.initState();
    final s = context.read<SettingsProvider>();
    _urlCtrl = TextEditingController(text: s.baseUrl);
    _devRefreshCtrl = TextEditingController(text: '${s.devicesRefreshSec}');
    _detailRefreshCtrl = TextEditingController(text: '${s.detailRefreshSec}');
  }

  @override
  void dispose() {
    _urlCtrl.dispose();
    _devRefreshCtrl.dispose();
    _detailRefreshCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<SettingsProvider>();
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _section('后端地址'),
          const SizedBox(height: 6),
          TextField(
            controller: _urlCtrl,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.link),
              labelText: 'base_url',
              hintText: 'http://127.0.0.1:8001',
            ),
            keyboardType: TextInputType.url,
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              FilledButton.icon(
                onPressed: () async {
                  await s.updateBaseUrl(_urlCtrl.text.trim());
                  if (!context.mounted) return;
                  await context.read<DevicesProvider>().refresh();
                  if (!context.mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('后端地址已更新')),
                  );
                },
                icon: const Icon(Icons.save),
                label: const Text('保存'),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: () => _testConnection(context),
                icon: const Icon(Icons.network_check),
                label: const Text('测试连接'),
              ),
            ],
          ),
          const Divider(height: 32),
          _section('刷新频率'),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _devRefreshCtrl,
                  decoration: const InputDecoration(
                    border: OutlineInputBorder(),
                    labelText: '设备列表 (秒)',
                  ),
                  keyboardType: TextInputType.number,
                  onSubmitted: (v) => s.updateDevicesRefreshSec(
                    int.tryParse(v) ?? s.devicesRefreshSec,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextField(
                  controller: _detailRefreshCtrl,
                  decoration: const InputDecoration(
                    border: OutlineInputBorder(),
                    labelText: '设备详情 (秒)',
                  ),
                  keyboardType: TextInputType.number,
                  onSubmitted: (v) => s.updateDetailRefreshSec(
                    int.tryParse(v) ?? s.detailRefreshSec,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          FilledButton.tonalIcon(
            onPressed: () async {
              final dv = int.tryParse(_devRefreshCtrl.text) ?? s.devicesRefreshSec;
              final dl = int.tryParse(_detailRefreshCtrl.text) ?? s.detailRefreshSec;
              await s.updateDevicesRefreshSec(dv);
              await s.updateDetailRefreshSec(dl);
              if (context.mounted) {
                context
                    .read<DevicesProvider>()
                    .updateInterval(Duration(seconds: dv));
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('刷新频率已更新')),
                );
              }
            },
            icon: const Icon(Icons.timer),
            label: const Text('应用刷新频率'),
          ),
          const Divider(height: 32),
          _section('联调工具'),
          const SizedBox(height: 6),
          Card(
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: BorderSide(
                color: Theme.of(context).dividerColor.withValues(alpha: 0.6),
              ),
            ),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '向 test1.py 上报一次模拟数据，用于快速验证后端是否在线。',
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      OutlinedButton.icon(
                        onPressed: () => _uploadDemo(context),
                        icon: const Icon(Icons.upload),
                        label: const Text('POST /upload 模拟'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 24),
          Center(
            child: Text(
              'HY Monitor · 对接 HY_Online/test1.py',
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: Theme.of(context).colorScheme.outline),
            ),
          ),
        ],
      ),
    );
  }

  Widget _section(String text) {
    return Text(
      text,
      style: Theme.of(context)
          .textTheme
          .titleSmall
          ?.copyWith(fontWeight: FontWeight.w700),
    );
  }

  Future<void> _testConnection(BuildContext context) async {
    final url = _urlCtrl.text.trim();
    if (url.isEmpty) return;
    final messenger = ScaffoldMessenger.of(context);
    messenger.showSnackBar(const SnackBar(
      content: Text('测试中…'),
      duration: Duration(seconds: 1),
    ));
    try {
      final api = ApiService(url);
      final ids = await api.listDevices();
      messenger.showSnackBar(SnackBar(
        content: Text('连接成功，当前共有 ${ids.length} 台设备'),
      ));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('连接失败: $e')));
    }
  }

  Future<void> _uploadDemo(BuildContext context) async {
    final settings = context.read<SettingsProvider>();
    final messenger = ScaffoldMessenger.of(context);
    final api = ApiService(settings.baseUrl);
    final demo = DeviceData(
      deviceId: 'demo_from_app',
      ddl: 0.123,
      ph: 7.25,
      phTemp: 25.0,
      pt100: 26.5,
      valves: const {'v1': true, 'v2': false, 'v3': true},
      isAlarming: false,
      fanSpeed: 1500,
      fanReadOk: true,
      running: true,
      interval: 2.0,
      lastUpdateTs: DateTime.now().millisecondsSinceEpoch / 1000.0,
    );
    try {
      final res = await api.uploadDeviceData(demo);
      messenger.showSnackBar(SnackBar(
        content: Text('上报成功: device=${res['device_id']}, count=${res['count']}'),
      ));
      if (context.mounted) {
        await context.read<DevicesProvider>().refresh();
      }
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('上报失败: $e')));
    }
  }
}
