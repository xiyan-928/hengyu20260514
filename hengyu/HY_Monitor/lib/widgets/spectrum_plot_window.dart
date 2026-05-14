import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../models/spectrum_data.dart';

const double _kSpectrumMinX = 200;
const double _kSpectrumMaxX = 1100;
const double _kSpectrumXInterval = 100;

class SpectrumPlotWindow extends StatelessWidget {
  const SpectrumPlotWindow({
    super.key,
    required this.title,
    required this.emptyText,
    required this.accentColor,
    required this.loading,
    required this.error,
    required this.data,
    this.series,
    required this.onClose,
  });

  final String title;
  final String emptyText;
  final Color accentColor;
  final bool loading;
  final String? error;
  final SpectrumData? data;
  final List<SpectrumPlotSeries>? series;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.8)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(Icons.show_chart, color: accentColor, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    title,
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w700),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                if (onClose != null)
                  IconButton(
                    tooltip: '关闭光谱图',
                    constraints: const BoxConstraints.tightFor(
                      width: 32,
                      height: 32,
                    ),
                    padding: EdgeInsets.zero,
                    visualDensity: VisualDensity.compact,
                    icon: const Icon(Icons.close),
                    iconSize: 20,
                    onPressed: onClose,
                  ),
              ],
            ),
            const SizedBox(height: 4),
            Container(
              height: 320,
              padding: const EdgeInsets.fromLTRB(8, 10, 14, 8),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerHighest
                    .withValues(alpha: 0.35),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(
                  color: theme.dividerColor.withValues(alpha: 0.6),
                ),
              ),
              clipBehavior: Clip.antiAlias,
              child: _body(context),
            ),
          ],
        ),
      ),
    );
  }

  Widget _body(BuildContext context) {
    final theme = Theme.of(context);
    if (loading && (series == null || series!.isEmpty)) {
      return const Center(child: CircularProgressIndicator());
    }
    if (error != null) {
      return Center(
        child: Text(
          '绘图失败: $error',
          style: TextStyle(color: theme.colorScheme.error),
          textAlign: TextAlign.center,
        ),
      );
    }
    final spectrum = data;
    final activeSeries = series ??
        (spectrum == null
            ? const <SpectrumPlotSeries>[]
            : [
                SpectrumPlotSeries(
                  label: title,
                  data: spectrum,
                  color: accentColor,
                ),
              ]);
    final drawableSeries =
        activeSeries.where((entry) => entry.data.spots.length >= 2).toList();
    if (activeSeries.isEmpty) {
      return Center(
        child: Text(
          emptyText,
          style: theme.textTheme.bodyMedium
              ?.copyWith(color: theme.colorScheme.outline),
          textAlign: TextAlign.center,
        ),
      );
    }
    if (drawableSeries.isEmpty) {
      return Center(
        child: Text(
          '坐标点不足，无法绘制光谱曲线',
          style: theme.textTheme.bodyMedium
              ?.copyWith(color: theme.colorScheme.outline),
        ),
      );
    }

    final firstSpectrum = drawableSeries.first.data;
    var minY = drawableSeries.first.data.spots.first.y;
    var maxY = minY;
    for (final entry in drawableSeries) {
      for (final spot in entry.data.spots) {
        if (spot.y < minY) minY = spot.y;
        if (spot.y > maxY) maxY = spot.y;
      }
    }
    (minY, maxY) = _padRange(minY, maxY);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (activeSeries.length > 1) ...[
          SizedBox(
            height: 32,
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final entry in activeSeries)
                    Padding(
                      padding: const EdgeInsets.only(right: 10),
                      child: _LegendItem(series: entry),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
        ],
        Expanded(
          child: LineChart(
            LineChartData(
              minX: _kSpectrumMinX,
              maxX: _kSpectrumMaxX,
              minY: minY,
              maxY: maxY,
              clipData: const FlClipData.all(),
              titlesData: FlTitlesData(
                topTitles:
                    const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                rightTitles:
                    const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                leftTitles: AxisTitles(
                  axisNameSize: 14,
                  axisNameWidget:
                      Text(firstSpectrum.ylabel, style: theme.textTheme.bodySmall),
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 46,
                    interval: _interval(minY, maxY),
                    getTitlesWidget: (v, meta) => Text(
                      _fmtK(v),
                      style: theme.textTheme.bodySmall,
                    ),
                  ),
                ),
                bottomTitles: AxisTitles(
                  axisNameSize: 16,
                  axisNameWidget:
                      Text(firstSpectrum.xlabel, style: theme.textTheme.bodySmall),
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 28,
                    interval: _kSpectrumXInterval,
                    getTitlesWidget: (v, meta) => Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(_fmtX(v), style: theme.textTheme.bodySmall),
                    ),
                  ),
                ),
              ),
              gridData: FlGridData(
                show: true,
                verticalInterval: _kSpectrumXInterval,
                horizontalInterval: _interval(minY, maxY),
                getDrawingHorizontalLine: (_) => FlLine(
                  color: theme.dividerColor.withValues(alpha: 0.4),
                  strokeWidth: 0.5,
                ),
                getDrawingVerticalLine: (_) => FlLine(
                  color: theme.dividerColor.withValues(alpha: 0.25),
                  strokeWidth: 0.5,
                ),
              ),
              borderData: FlBorderData(
                show: true,
                border:
                    Border.all(color: theme.dividerColor.withValues(alpha: 0.6)),
              ),
              lineBarsData: [
                for (final entry in drawableSeries)
                  LineChartBarData(
                    spots: entry.data.spots,
                    isCurved: false,
                    color: entry.color,
                    barWidth: 1.4,
                    dotData: FlDotData(show: entry.data.spots.length <= 80),
                    belowBarData: BarAreaData(
                      show: true,
                      color: entry.color.withValues(alpha: 0.04),
                    ),
                  ),
              ],
              lineTouchData: LineTouchData(
                touchTooltipData: LineTouchTooltipData(
                  getTooltipItems: (items) => items
                      .map(
                        (item) {
                          final label = item.barIndex >= 0 &&
                                  item.barIndex < drawableSeries.length
                              ? drawableSeries[item.barIndex].label
                              : '光谱';
                          return LineTooltipItem(
                            '$label\nx: ${_fmtX(item.x)}\ny: ${_fmtK(item.y)}',
                            TextStyle(
                              color: theme.colorScheme.onSurface,
                              fontWeight: FontWeight.w500,
                            ),
                          );
                        },
                      )
                      .toList(),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  static (double, double) _padRange(double min, double max) {
    if ((max - min).abs() < 1e-12) {
      return (min - 1, max + 1);
    }
    final pad = (max - min).abs() * 0.05;
    return (min - pad, max + pad);
  }

  static double _interval(double min, double max) {
    final span = (max - min).abs();
    if (span < 1e-12) return 1;
    return span / 4;
  }

  static String _fmtX(double value) => value.toStringAsFixed(0);

  static String _fmtK(double value) => '${(value / 1000).toStringAsFixed(1)}k';
}

class SpectrumPlotSeries {
  const SpectrumPlotSeries({
    required this.label,
    required this.data,
    required this.color,
  });

  final String label;
  final SpectrumData data;
  final Color color;
}

class _LegendItem extends StatelessWidget {
  const _LegendItem({required this.series});

  final SpectrumPlotSeries series;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(
            color: series.color,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 5),
        Text(
          series.label,
          style: theme.textTheme.bodySmall,
          overflow: TextOverflow.ellipsis,
        ),
      ],
    );
  }
}
