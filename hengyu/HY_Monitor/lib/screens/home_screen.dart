import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../models/device_data.dart';
import '../providers/devices_provider.dart';
import '../widgets/connection_status_bar.dart';
import 'device_detail_screen.dart';
import 'settings_screen.dart';
import 'spectrum_search_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('HY Monitor · 设备总览'),
        actions: [
          IconButton(
            tooltip: '光谱检索',
            icon: const Icon(Icons.manage_search_rounded),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => const SpectrumSearchScreen(),
              ),
            ),
          ),
          IconButton(
            tooltip: '刷新',
            icon: const Icon(Icons.refresh),
            onPressed: () => context.read<DevicesProvider>().refresh(),
          ),
          IconButton(
            tooltip: '设置',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => const SettingsScreen(),
              ),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          const ConnectionStatusBar(),
          Expanded(
            child: Consumer<DevicesProvider>(
              builder: (context, p, _) {
                if (p.error != null && p.deviceIds.isEmpty) {
                  return _ErrorState(message: p.error!);
                }
                if (p.deviceIds.isEmpty && p.loading) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (p.deviceIds.isEmpty) {
                  return const _EmptyState();
                }
                return RefreshIndicator(
                  onRefresh: p.refresh,
                  child: ListView.separated(
                    padding: const EdgeInsets.all(12),
                    itemCount: p.deviceIds.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 10),
                    itemBuilder: (context, index) {
                      final id = p.deviceIds[index];
                      return _DeviceTile(
                        deviceId: id,
                        data: p.latestByDevice[id],
                        perDeviceError: p.errorFor(id),
                      );
                    },
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _DeviceTile extends StatelessWidget {
  const _DeviceTile({
    required this.deviceId,
    required this.data,
    required this.perDeviceError,
  });

  final String deviceId;
  final DeviceData? data;
  final String? perDeviceError;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final alarming = data?.isAlarming == true;
    final running = data?.running ?? true;

    Color statusColor;
    IconData statusIcon;
    String statusText;
    if (perDeviceError != null && data == null) {
      statusColor = theme.colorScheme.outline;
      statusIcon = Icons.help_outline;
      statusText = '离线';
    } else if (alarming) {
      statusColor = Colors.red;
      statusIcon = Icons.warning_amber_rounded;
      statusText = '告警';
    } else if (!running) {
      statusColor = Colors.orange;
      statusIcon = Icons.pause_circle_outline;
      statusText = '已暂停';
    } else {
      statusColor = Colors.green;
      statusIcon = Icons.check_circle_outline;
      statusText = '正常';
    }

    final subtitleChildren = <Widget>[];
    if (data != null) {
      subtitleChildren.add(
        Wrap(
          spacing: 12,
          runSpacing: 6,
          children: [
            _miniMetric('DDL', data!.ddl.toStringAsFixed(3)),
            _miniMetric('pH', data!.ph.toStringAsFixed(2)),
            _miniMetric('PT100', '${data!.pt100.toStringAsFixed(2)}°C'),
            _miniMetric('风机', '${data!.fanSpeed} rpm'),
          ],
        ),
      );
      final ts = data!.timestamp;
      if (ts != null) {
        subtitleChildren.add(const SizedBox(height: 6));
        subtitleChildren.add(
          Text(
            '最近上报 ${DateFormat('yyyy-MM-dd HH:mm:ss').format(ts)}',
            style: theme.textTheme.bodySmall
                ?.copyWith(color: theme.colorScheme.outline),
          ),
        );
      }
    } else if (perDeviceError != null) {
      subtitleChildren.add(
        Text(
          '读取失败: $perDeviceError',
          style: theme.textTheme.bodySmall?.copyWith(color: Colors.red),
        ),
      );
    }

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.6)),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => DeviceDetailScreen(deviceId: deviceId),
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: statusColor.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(statusIcon, color: statusColor, size: 24),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            deviceId,
                            style: theme.textTheme.titleMedium
                                ?.copyWith(fontWeight: FontWeight.w600),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(
                            color: statusColor.withValues(alpha: 0.12),
                            borderRadius: BorderRadius.circular(20),
                          ),
                          child: Text(
                            statusText,
                            style: TextStyle(
                              color: statusColor,
                              fontWeight: FontWeight.w600,
                              fontSize: 12,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    ...subtitleChildren,
                  ],
                ),
              ),
              const SizedBox(width: 4),
              Icon(Icons.chevron_right, color: theme.colorScheme.outline),
            ],
          ),
        ),
      ),
    );
  }

  Widget _miniMetric(String label, String value) {
    return Builder(builder: (context) {
      final theme = Theme.of(context);
      return RichText(
        text: TextSpan(
          style: theme.textTheme.bodyMedium,
          children: [
            TextSpan(
              text: '$label ',
              style: TextStyle(color: theme.colorScheme.outline),
            ),
            TextSpan(
              text: value,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ],
        ),
      );
    });
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.devices_other,
                size: 64, color: theme.colorScheme.outline),
            const SizedBox(height: 12),
            Text(
              '后端还没有收到任何设备上报',
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: 6),
            Text(
              '确认 test1.py 正在运行，并有边缘端往 /upload 上报数据。',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.cloud_off_rounded,
                size: 64, color: theme.colorScheme.error),
            const SizedBox(height: 12),
            Text('连接后端失败',
                style: theme.textTheme.titleMedium
                    ?.copyWith(color: theme.colorScheme.error)),
            const SizedBox(height: 8),
            Text(
              message,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
            const SizedBox(height: 12),
            FilledButton.tonalIcon(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => const SettingsScreen(),
                ),
              ),
              icon: const Icon(Icons.settings),
              label: const Text('前往设置检查 base_url'),
            ),
          ],
        ),
      ),
    );
  }
}
