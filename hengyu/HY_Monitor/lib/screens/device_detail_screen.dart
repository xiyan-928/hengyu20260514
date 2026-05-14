import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../models/device_data.dart';
import '../providers/device_detail_provider.dart';
import '../providers/settings_provider.dart';
import '../services/api_service.dart';
import '../widgets/alarm_banner.dart';
import '../widgets/metric_card.dart';
import '../widgets/valve_chip_panel.dart';
import 'blank_spc_screen.dart';
import 'device_history_screen.dart';
import 'spc_files_screen.dart';

class DeviceDetailScreen extends StatefulWidget {
  const DeviceDetailScreen({super.key, required this.deviceId});

  final String deviceId;

  @override
  State<DeviceDetailScreen> createState() => _DeviceDetailScreenState();
}

class _DeviceDetailScreenState extends State<DeviceDetailScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tab = TabController(length: 4, vsync: this);
  bool _tabsVisible = false;

  // Provider 在 initState 里创建，不受父级 rebuild 影响。
  late final DeviceDetailProvider _provider;

  @override
  void initState() {
    super.initState();
    final settings = context.read<SettingsProvider>();
    _provider = DeviceDetailProvider(
      ApiService(settings.baseUrl),
      widget.deviceId,
    )
      ..startLatestPolling(
        interval: Duration(seconds: settings.detailRefreshSec),
      )
      ..refreshHistory()
      ..refreshBatches(autoSelectLatest: true);

    // 切换到历史 Tab 时自动拉取最新历史记录
    _tab.addListener(_onTabChanged);
  }

  void _onTabChanged() async {
    if (!_tab.indexIsChanging) return;
    if (_tab.index == 1) {
      _provider.refreshHistory();
    } else if (_tab.index == 2) {
      await _provider.ensureBatchSelected();
      await _provider.refreshSpcFiles();
    } else if (_tab.index == 3) {
      await _provider.ensureBatchSelected();
      await _provider.refreshBlankSpcFiles();
    }
  }

  @override
  void dispose() {
    _tab.removeListener(_onTabChanged);
    _tab.dispose();
    _provider.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider.value(
      value: _provider,
      child: Scaffold(
        appBar: AppBar(
          title: Text(widget.deviceId),
        ),
        body: Stack(
          children: [
            TabBarView(
              controller: _tab,
              physics: const NeverScrollableScrollPhysics(),
              children: [
                _LatestTab(deviceId: widget.deviceId),
                DeviceHistoryScreen(deviceId: widget.deviceId),
                SpcFilesScreen(deviceId: widget.deviceId),
                BlankSpcScreen(deviceId: widget.deviceId),
              ],
            ),
            Positioned(
              top: 0,
              left: 0,
              right: 0,
              height: 10,
              child: MouseRegion(
                onEnter: (_) => setState(() => _tabsVisible = true),
                child: const SizedBox.expand(),
              ),
            ),
            AnimatedPositioned(
              duration: const Duration(milliseconds: 180),
              curve: Curves.easeOut,
              top: _tabsVisible ? 0 : -56,
              left: 0,
              right: 0,
              height: 56,
              child: MouseRegion(
                onEnter: (_) => setState(() => _tabsVisible = true),
                onExit: (_) => setState(() => _tabsVisible = false),
                child: Material(
                  elevation: 4,
                  color: Theme.of(context).colorScheme.surface,
                  child: TabBar(
                    controller: _tab,
                    tabs: const [
                      Tab(icon: Icon(Icons.speed), text: '实时'),
                      Tab(icon: Icon(Icons.show_chart), text: '历史'),
                      Tab(icon: Icon(Icons.folder_open), text: 'SPC'),
                      Tab(icon: Icon(Icons.science_outlined), text: '参比光谱'),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _LatestTab extends StatelessWidget {
  const _LatestTab({required this.deviceId});

  final String deviceId;

  @override
  Widget build(BuildContext context) {
    return Consumer<DeviceDetailProvider>(
      builder: (context, p, _) {
        if (p.latest == null && p.latestLoading) {
          return const Center(child: CircularProgressIndicator());
        }
        if (p.latest == null) {
          return _ErrorBody(
            message: p.latestError ?? '暂无数据',
            onRetry: p.refreshLatest,
          );
        }
        final d = p.latest!;
        return RefreshIndicator(
          onRefresh: p.refreshLatest,
          child: SingleChildScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                AlarmBanner(alarming: d.isAlarming, lastError: d.lastError),
                const SizedBox(height: 12),
                _metricGrid(context, d),
                const SizedBox(height: 16),
                _SectionTitle(
                  '阀门状态',
                  trailing: _Heartbeat(data: d),
                ),
                const SizedBox(height: 8),
                ValveChipPanel(valves: d.valves),
                const SizedBox(height: 16),
                const _SectionTitle('状态详情'),
                const SizedBox(height: 8),
                _InfoTable(data: d),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _metricGrid(BuildContext context, DeviceData d) {
    final items = <Widget>[
      MetricCard(
        label: 'DDL',
        value: d.ddl.toStringAsFixed(3),
        unit: 'au',
        icon: Icons.opacity,
        color: Colors.indigo,
      ),
      MetricCard(
        label: 'pH',
        value: d.ph.toStringAsFixed(2),
        icon: Icons.science_outlined,
        color: Colors.teal,
      ),
      MetricCard(
        label: 'pH 温度',
        value: d.phTemp.toStringAsFixed(2),
        unit: '°C',
        icon: Icons.thermostat,
        color: Colors.deepOrange,
      ),
      MetricCard(
        label: 'PT100',
        value: d.pt100.toStringAsFixed(2),
        unit: '°C',
        icon: Icons.device_thermostat,
        color: Colors.orange,
      ),
      MetricCard(
        label: '风机转速',
        value: d.fanSpeed.toString(),
        unit: 'rpm',
        icon: Icons.air,
        color: d.fanReadOk ? Colors.blue : Colors.red,
        sub: d.fanReadOk ? '读取正常' : (d.fanLastError ?? '读取失败'),
      ),
      MetricCard(
        label: '采集间隔',
        value: d.interval.toStringAsFixed(1),
        unit: 's',
        icon: Icons.timer_outlined,
        color: Colors.purple,
        sub: d.running ? '正在采集' : '已暂停',
      ),
      // ---- BridgeDataManager 字段 ----
      MetricCard(
        label: '桥接温度',
        value: d.temperature.toStringAsFixed(2),
        unit: '°C',
        icon: Icons.whatshot_outlined,
        color: d.temperature > 85
            ? Colors.red
            : (d.temperature > 45 ? Colors.deepOrange : Colors.green),
        sub: d.bridgeState == 'triggered' ? '已触发' : '待机',
      ),
      MetricCard(
        label: '液位',
        value: d.level.toStringAsFixed(4),
        icon: Icons.water_drop_outlined,
        color: Colors.cyan,
        sub: d.bridgeError != null ? '读取异常' : '正常',
      ),
    ];
    return LayoutBuilder(
      builder: (context, cst) {
        final w = cst.maxWidth;
        final cross =w > 1600 ? 8 : (w > 900 ? 6 : (w > 560 ? 4 : 3));
        return GridView.count(
          crossAxisCount: cross,
          crossAxisSpacing: 10,
          mainAxisSpacing: 10,
          childAspectRatio: cross == 1 ? 2.0 : 1.7,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          children: items,
        );
      },
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text, {this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(
          text,
          style: Theme.of(context)
              .textTheme
              .titleSmall
              ?.copyWith(fontWeight: FontWeight.w700),
        ),
        const Spacer(),
        if (trailing != null) trailing!,
      ],
    );
  }
}

class _Heartbeat extends StatelessWidget {
  const _Heartbeat({required this.data});
  final DeviceData data;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ts = data.timestamp;
    final txt = ts != null
        ? '最近上报 ${DateFormat('HH:mm:ss').format(ts)}'
        : '无时间戳';
    return Text(
      txt,
      style: theme.textTheme.bodySmall
          ?.copyWith(color: theme.colorScheme.outline),
    );
  }
}

class _InfoTable extends StatelessWidget {
  const _InfoTable({required this.data});
  final DeviceData data;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = <(String, String)>[
      ('device_id', data.deviceId),
      ('server_time', data.serverTime ?? '—'),
      ('running', data.running.toString()),
      ('interval', '${data.interval.toStringAsFixed(1)} s'),
      ('fan_read_ok', data.fanReadOk.toString()),
      ('fan_last_error', data.fanLastError ?? '—'),
      ('fan_last_read_ts', _fmtTs(data.fanLastReadTs)),
      ('last_update_ts', _fmtTs(data.lastUpdateTs)),
      ('last_error', data.lastError ?? '—'),
      // ---- BridgeDataManager ----
      ('bridge_state', data.bridgeState),
      ('bridge_error', data.bridgeError ?? '—'),
      ('bridge_last_update_ts', _fmtTs(data.bridgeLastUpdateTs)),
    ];
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.6)),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        child: Column(
          children: [
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(
                      width: 140,
                      child: Text(
                        row.$1,
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.outline),
                      ),
                    ),
                    Expanded(
                      child: Text(
                        row.$2,
                        style: theme.textTheme.bodyMedium,
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _fmtTs(double? v) {
    if (v == null) return '—';
    final dt = DateTime.fromMillisecondsSinceEpoch((v * 1000).round());
    return DateFormat('yyyy-MM-dd HH:mm:ss').format(dt);
  }
}

class _ErrorBody extends StatelessWidget {
  const _ErrorBody({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_outlined, size: 52),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton.tonalIcon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }
}
