import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:intl/intl.dart';
import '../models/absorbance_data.dart';

class AbsorbanceChart extends StatefulWidget {
  final List<AbsorbanceData> absorbanceData;
  final double height;

  const AbsorbanceChart({
    super.key,
    required this.absorbanceData,
    this.height = 120,
  });

  @override
  State<AbsorbanceChart> createState() => _AbsorbanceChartState();
}

class _AbsorbanceChartState extends State<AbsorbanceChart> {
  // 缓存优化
  List<FlSpot>? _cachedSpots;
  int _lastDataHash = 0;

  @override
  void didUpdateWidget(AbsorbanceChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 检查数据是否变化，如果变化则清除缓存
    final newDataHash = _calculateDataHash();
    if (newDataHash != _lastDataHash) {
      _cachedSpots = null;
      _lastDataHash = newDataHash;
    }
  }

  // 计算数据哈希值用于缓存比较
  int _calculateDataHash() {
    int hash = 0;
    hash ^= widget.absorbanceData.length.hashCode;
    if (widget.absorbanceData.isNotEmpty) {
      hash ^= widget.absorbanceData.last.timestamp.millisecondsSinceEpoch.hashCode;
      hash ^= widget.absorbanceData.last.value.hashCode;
    }
    return hash;
  }

  @override
  Widget build(BuildContext context) {
    if (widget.absorbanceData.isEmpty) {
      return Container(
        height: widget.height,
        decoration: BoxDecoration(
          color: Colors.grey.shade50,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.grey.shade200),
        ),
        child: Center(
          child: Text(
            '暂无吸光度历史数据',
            style: TextStyle(
              color: Colors.grey.shade600,
              fontSize: 12,
            ),
          ),
        ),
      );
    }

    return Container(
      height: widget.height,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.blue.shade200),
      ),
      child: Padding(
        padding: const EdgeInsets.all(8.0),
        child: LineChart(
          LineChartData(
            gridData: FlGridData(
              show: true,
              drawVerticalLine: false,
              horizontalInterval: _getHorizontalInterval(),
              getDrawingHorizontalLine: (value) {
                return FlLine(
                  color: Colors.grey.shade300,
                  strokeWidth: 0.5,
                );
              },
            ),
            titlesData: FlTitlesData(
              leftTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 35,
                  interval: _getHorizontalInterval(),
                  getTitlesWidget: (value, meta) {
                    return Text(
                      value.toStringAsFixed(1),
                      style: TextStyle(
                        color: Colors.grey.shade600,
                        fontSize: 10,
                      ),
                    );
                  },
                ),
              ),
              bottomTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 20,
                  interval: _getTimeInterval(),
                  getTitlesWidget: (value, meta) {
                    final time = DateTime.fromMillisecondsSinceEpoch(value.toInt());
                    return Text(
                      DateFormat('HH:mm').format(time),
                      style: TextStyle(
                        color: Colors.grey.shade600,
                        fontSize: 9,
                      ),
                    );
                  },
                ),
              ),
              topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
              rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
            ),
            borderData: FlBorderData(show: false),
            lineBarsData: [
              LineChartBarData(
                spots: _getOptimizedSpots(),
                isCurved: true,
                color: Colors.blue.shade600,
                barWidth: 2,
                isStrokeCapRound: true,
                dotData: FlDotData(
                  show: false,
                ),
                belowBarData: BarAreaData(
                  show: true,
                  color: Colors.blue.shade600.withOpacity(0.1),
                ),
              ),
            ],
            minX: _getMinX(),
            maxX: _getMaxX(),
            minY: _getMinY(),
            maxY: _getMaxY(),
          ),
        ),
      ),
    );
  }

  List<FlSpot> _getOptimizedSpots() {
    if (_cachedSpots != null) {
      return _cachedSpots!;
    }

    final sortedData = List<AbsorbanceData>.from(widget.absorbanceData)
      ..sort((a, b) => a.timestamp.compareTo(b.timestamp));

    _cachedSpots = sortedData.map((data) {
      return FlSpot(
        data.timestamp.millisecondsSinceEpoch.toDouble(),
        data.value,
      );
    }).toList();

    return _cachedSpots!;
  }

  double _getMinX() {
    if (widget.absorbanceData.isEmpty) return 0;
    return widget.absorbanceData
        .map((data) => data.timestamp.millisecondsSinceEpoch.toDouble())
        .reduce((a, b) => a < b ? a : b);
  }

  double _getMaxX() {
    if (widget.absorbanceData.isEmpty) return 1;
    return widget.absorbanceData
        .map((data) => data.timestamp.millisecondsSinceEpoch.toDouble())
        .reduce((a, b) => a > b ? a : b);
  }

  double _getMinY() {
    if (widget.absorbanceData.isEmpty) return 0;
    final minValue = widget.absorbanceData
        .map((data) => data.value)
        .reduce((a, b) => a < b ? a : b);
    return (minValue * 0.95).clamp(0.0, double.infinity);
  }

  double _getMaxY() {
    if (widget.absorbanceData.isEmpty) return 100;
    final maxValue = widget.absorbanceData
        .map((data) => data.value)
        .reduce((a, b) => a > b ? a : b);
    return (maxValue * 1.05).clamp(0.0, double.infinity);
  }

  double _getHorizontalInterval() {
    final range = _getMaxY() - _getMinY();
    if (range <= 10) return 1;
    if (range <= 50) return 5;
    if (range <= 100) return 10;
    return 20;
  }

  double _getTimeInterval() {
    final timeRange = _getMaxX() - _getMinX();
    final minutes = timeRange / (1000 * 60);
    
    if (minutes <= 5) return 1000 * 60; // 1 minute
    if (minutes <= 30) return 1000 * 60 * 5; // 5 minutes
    if (minutes <= 120) return 1000 * 60 * 15; // 15 minutes
    return 1000 * 60 * 30; // 30 minutes
  }
}
