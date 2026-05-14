import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../models/device_data.dart';
import '../providers/device_detail_provider.dart';
import '../widgets/process_parameters_sidebar.dart';

class DeviceHistoryScreen extends StatefulWidget {
  const DeviceHistoryScreen({super.key, required this.deviceId});

  final String deviceId;

  @override
  State<DeviceHistoryScreen> createState() => _DeviceHistoryScreenState();
}

class _DeviceHistoryScreenState extends State<DeviceHistoryScreen> {
  _Metric _selected = _Metric.ddl;

  @override
  void initState() {
    super.initState();
    // 进入历史页时拉取批次列表，并自动选中"最新（正在采集）"那个批次。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      context
          .read<DeviceDetailProvider>()
          .refreshBatches(autoSelectLatest: true);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<DeviceDetailProvider>(
      builder: (context, p, _) {
        final history = p.displayHistory;
        final loading = p.displayHistoryLoading;
        final Widget child;
        if (history.isEmpty && loading) {
          child = const Center(child: CircularProgressIndicator());
        } else if (history.isEmpty) {
          child = _empty(context, p);
        } else {
          child = _body(context, p);
        }
        return LayoutBuilder(
          builder: (context, constraints) => RefreshIndicator(
            onRefresh: () async {
              await p.refreshBatches();
              await p.refreshSelectedBatch();
            },
            child: SingleChildScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              child: SizedBox(
                height: constraints.maxHeight,
                child: child,
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _empty(BuildContext context, DeviceDetailProvider p) {
    final theme = Theme.of(context);
    final err = p.displayHistoryError;
    final emptyMsg = p.selectedBatch == null
        ? '尚无任何生产批次数据'
        : '该批次暂无记录：${p.selectedBatch}';
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.auto_graph_outlined,
              size: 56, color: theme.colorScheme.outline),
          const SizedBox(height: 12),
          Text(err ?? emptyMsg),
          const SizedBox(height: 10),
          FilledButton.tonalIcon(
            onPressed: () async {
              await p.refreshBatches(autoSelectLatest: p.selectedBatch == null);
              await p.refreshSelectedBatch();
            },
            icon: const Icon(Icons.refresh),
            label: const Text('刷新'),
          ),
        ],
      ),
    );
  }

  Widget _body(BuildContext context, DeviceDetailProvider p) {
    final history = p.displayHistory;
    final theme = Theme.of(context);
    final metaSource = history.isNotEmpty ? history.last : null;

    final mainColumn = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                p.selectedBatch == null
                    ? '共 ${history.length} 个样本'
                    : '批次 ${p.selectedBatch} · ${history.length} 个样本',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: theme.colorScheme.outline),
              ),
            ),
            TextButton.icon(
              onPressed: p.displayHistoryLoading
                  ? null
                  : p.refreshSelectedBatch,
              icon: const Icon(Icons.refresh),
              label: const Text('重新加载'),
            ),
          ],
        ),
        const SizedBox(height: 4),
        SizedBox(
          height: 40,
          child: ListView(
            scrollDirection: Axis.horizontal,
            children: [
              for (final m in _Metric.values)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(m.label),
                    selected: _selected == m,
                    onSelected: (_) => setState(() => _selected = m),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        Expanded(child: _chart(context, history)),
      ],
    );

    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 560;
        final sidebar = ProcessParametersSidebar(
          provider: p,
          data: metaSource,
        );

        return Padding(
          padding: const EdgeInsets.all(12),
          child: wide
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SizedBox(width: 252, child: sidebar),
                    const SizedBox(width: 12),
                    Expanded(child: mainColumn),
                  ],
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    sidebar,
                    const SizedBox(height: 12),
                    Expanded(child: mainColumn),
                  ],
                ),
        );
      },
    );
  }

  Widget _chart(BuildContext context, List<DeviceData> history) {
    final theme = Theme.of(context);
    final spots = <FlSpot>[];
    for (var i = 0; i < history.length; i++) {
      final d = history[i];
      final y = _selected.extract(d);
      spots.add(FlSpot(i.toDouble(), y));
    }
    if (spots.isEmpty) {
      return const Center(child: Text('没有可绘制的样本'));
    }
    // fl_chart 要求 minX < maxX；单条记录时无法绘制折线
    if (spots.length < 2) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.show_chart,
                size: 48, color: theme.colorScheme.outline),
            const SizedBox(height: 12),
            Text(
              '历史记录不足（当前 ${spots.length} 条），\n至少需要 2 条才能显示趋势曲线。',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
          ],
        ),
      );
    }

    double minY = spots.first.y, maxY = spots.first.y;
    for (final s in spots) {
      if (s.y < minY) minY = s.y;
      if (s.y > maxY) maxY = s.y;
    }
    if ((maxY - minY).abs() < 1e-9) {
      minY -= 1;
      maxY += 1;
    } else {
      final pad = (maxY - minY) * 0.1;
      minY -= pad;
      maxY += pad;
    }

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.6)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 20, 20, 12),
        child: LineChart(
          LineChartData(
            minX: 0,
            maxX: (spots.length - 1).toDouble(),
            minY: minY,
            maxY: maxY,
            titlesData: FlTitlesData(
              topTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false)),
              rightTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false)),
              leftTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 48,
                  getTitlesWidget: (v, meta) => Text(
                    v.toStringAsFixed(2),
                    style: theme.textTheme.bodySmall,
                  ),
                ),
              ),
              bottomTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 28,
                  interval: (spots.length / 4).clamp(1, double.infinity),
                  getTitlesWidget: (v, meta) {
                    final i = v.toInt();
                    if (i < 0 || i >= history.length) {
                      return const SizedBox.shrink();
                    }
                    final ts = history[i].timestamp;
                    if (ts == null) return const SizedBox.shrink();
                    return Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        DateFormat('HH:mm:ss').format(ts),
                        style: theme.textTheme.bodySmall,
                      ),
                    );
                  },
                ),
              ),
            ),
            gridData: FlGridData(
              show: true,
              getDrawingHorizontalLine: (_) => FlLine(
                color: theme.dividerColor.withValues(alpha: 0.4),
                strokeWidth: 0.5,
              ),
              drawVerticalLine: false,
            ),
            borderData: FlBorderData(
              show: true,
              border: Border.all(color: theme.dividerColor.withValues(alpha: 0.6)),
            ),
            lineBarsData: [
              LineChartBarData(
                spots: spots,
                isCurved: false,
                color: _selected.color,
                barWidth: 2,
                dotData: FlDotData(
                  show: spots.length < 60,
                  getDotPainter: (s, _, __, ___) => FlDotCirclePainter(
                    radius: 2.5,
                    color: _selected.color,
                    strokeWidth: 0,
                  ),
                ),
                belowBarData: BarAreaData(
                  show: true,
                  color: _selected.color.withValues(alpha: 0.08),
                ),
              ),
            ],
            lineTouchData: LineTouchData(
              touchTooltipData: LineTouchTooltipData(
                getTooltipItems: (items) => items.map((ts) {
                  final i = ts.x.toInt();
                  final dt = (i >= 0 && i < history.length)
                      ? history[i].timestamp
                      : null;
                  final timeText = dt != null
                      ? DateFormat('MM-dd HH:mm:ss').format(dt)
                      : '样本 #$i';
                  return LineTooltipItem(
                    '$timeText\n${_selected.label}: ${ts.y.toStringAsFixed(3)}${_selected.unit}',
                    TextStyle(
                      color: theme.colorScheme.onSurface,
                      fontWeight: FontWeight.w500,
                    ),
                  );
                }).toList(),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

enum _Metric {
  ddl('DDL', '', Colors.indigo),
  ph('pH', '', Colors.teal),
  phTemp('pH 温度', '°C', Colors.deepOrange),
  pt100('PT100', '°C', Colors.orange),
  fanSpeed('风机转速', ' rpm', Colors.blue),
  // ---- BridgeDataManager ----
  temperature('桥接温度', '°C', Colors.red),
  level('液位', '', Colors.cyan);

  const _Metric(this.label, this.unit, this.color);
  final String label;
  final String unit;
  final Color color;

  double extract(DeviceData d) {
    switch (this) {
      case _Metric.ddl:
        return d.ddl;
      case _Metric.ph:
        return d.ph;
      case _Metric.phTemp:
        return d.phTemp;
      case _Metric.pt100:
        return d.pt100;
      case _Metric.fanSpeed:
        return d.fanSpeed.toDouble();
      case _Metric.temperature:
        return d.temperature;
      case _Metric.level:
        return d.level;
    }
  }
}
