import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../providers/devices_provider.dart';
import '../providers/settings_provider.dart';

/// 顶部（AppBar 之下）的一行状态条：后端地址 + 在线/离线 + 最近刷新时刻。
class ConnectionStatusBar extends StatelessWidget {
  const ConnectionStatusBar({super.key});

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<SettingsProvider>();
    final devices = context.watch<DevicesProvider>();
    final theme = Theme.of(context);

    final online = devices.isOnline;
    final color = online ? Colors.green : theme.colorScheme.error;
    final refreshedAt = devices.lastRefreshAt;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
      child: Row(
        children: [
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '${online ? "已连接" : "未连接"}  ·  ${settings.baseUrl}',
              style: theme.textTheme.bodySmall,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (refreshedAt != null)
            Text(
              '刷新 ${DateFormat('HH:mm:ss').format(refreshedAt)}',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.outline,
              ),
            ),
          const SizedBox(width: 6),
          if (devices.loading)
            const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
        ],
      ),
    );
  }
}
