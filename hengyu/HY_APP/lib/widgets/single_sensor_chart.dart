import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:intl/intl.dart';
import '../models/sensor_data.dart';

class SingleSensorChart extends StatefulWidget {
  final String sensorType;
  final List<SensorData> sensorData;
  final double height;

  const SingleSensorChart({
    super.key,
    required this.sensorType,
    required this.sensorData,
    this.height = 120,
  });

  @override
  State<SingleSensorChart> createState() => _SingleSensorChartState();
}

class _SingleSensorChartState extends State<SingleSensorChart> {
  // 缓存优化
  List<FlSpot>? _cachedSpots;
  int _lastDataHash = 0;

  @override
  void didUpdateWidget(SingleSensorChart oldWidget) {
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
    hash ^= widget.sensorData.length.hashCode;
    if (widget.sensorData.isNotEmpty) {
      hash ^= widget.sensorData.last.timestamp.millisecondsSinceEpoch.hashCode;
      hash ^= widget.sensorData.last.value.hashCode;
    }
    return hash;
  }

  @override
  Widget build(BuildContext context) {
    if (widget.sensorData.isEmpty) {
      return Container(
        height: widget.height,
        decoration: BoxDecoration(
          color: Colors.grey.shade50,
          borderRadius: BorderRadius.circular(4),
        ),
        child: Center(
          child: Text(
            '无数据',
            style: TextStyle(
              fontSize: 10,
              color: Colors.grey.shade500,
            ),
          ),
        ),
      );
    }

    return Container(
      height: widget.height,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(4),
      ),
      child: LineChart(
        LineChartData(
          lineBarsData: [_buildLineData()],
          titlesData: _buildTitles(),
          gridData: FlGridData(
            show: true,
            drawVerticalLine: false,
            horizontalInterval: _calculateOptimalValueInterval(),
            getDrawingHorizontalLine: (value) {
              return FlLine(
                color: Colors.grey.shade200,
                strokeWidth: 0.5,
              );
            },
          ),
          borderData: FlBorderData(show: false),
          lineTouchData: LineTouchData(
            enabled: true,
            touchTooltipData: LineTouchTooltipData(
              getTooltipItems: _buildTooltipItems,
            ),
          ),
          // 性能优化设置
          clipData: const FlClipData.all(),
          backgroundColor: Colors.transparent,
        ),
      ),
    );
  }

  LineChartBarData _buildLineData() {
    final spots = _getCachedSpots();
    
    return LineChartBarData(
      spots: spots,
      color: _getSensorColor(widget.sensorType),
      barWidth: 1.5,
      isStrokeCapRound: true,
      dotData: FlDotData(
        show: spots.length <= 10, // 只在数据点少的时候显示点
        getDotPainter: (spot, percent, barData, index) {
          return FlDotCirclePainter(
            radius: 2,
            color: _getSensorColor(widget.sensorType),
            strokeWidth: 0,
          );
        },
      ),
      belowBarData: BarAreaData(
        show: true,
        color: _getSensorColor(widget.sensorType).withOpacity(0.1),
      ),
      // 性能优化设置
      preventCurveOverShooting: true,
      preventCurveOvershootingThreshold: 5,
    );
  }

  FlTitlesData _buildTitles() {
    return FlTitlesData(
      rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
      topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
      bottomTitles: AxisTitles(
        sideTitles: SideTitles(
          showTitles: true,
          reservedSize: 20,
          interval: _calculateOptimalTimeInterval(),
          getTitlesWidget: (value, meta) {
            final timestamp = DateTime.fromMillisecondsSinceEpoch(value.toInt());
            return SideTitleWidget(
              axisSide: meta.axisSide,
              child: Text(
                DateFormat('HH:mm').format(timestamp),
                style: const TextStyle(
                  color: Colors.grey,
                  fontSize: 8,
                ),
              ),
            );
          },
        ),
      ),
      leftTitles: AxisTitles(
        sideTitles: SideTitles(
          showTitles: true,
          reservedSize: 30,
          interval: _calculateOptimalValueInterval(),
          getTitlesWidget: (value, meta) {
            return SideTitleWidget(
              axisSide: meta.axisSide,
              child: Text(
                _formatAxisValue(value),
                style: const TextStyle(
                  color: Colors.grey,
                  fontSize: 8,
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  // 获取缓存的数据点
  List<FlSpot> _getCachedSpots() {
    if (_cachedSpots == null) {
      _cachedSpots = _createOptimizedSpots(widget.sensorData);
    }
    return _cachedSpots!;
  }

  // 优化的数据点创建方法
  List<FlSpot> _createOptimizedSpots(List<SensorData> sensorDataList) {
    if (sensorDataList.isEmpty) return [];
    
    // 对于小图表，最多显示20个点
    final maxPoints = 20;
    final step = sensorDataList.length > maxPoints ? sensorDataList.length ~/ maxPoints : 1;
    
    final spots = <FlSpot>[];
    for (int i = 0; i < sensorDataList.length; i += step) {
      final data = sensorDataList[i];
      spots.add(FlSpot(
        data.timestamp.millisecondsSinceEpoch.toDouble(),
        data.value,
      ));
    }
    
    // 确保包含最后一个数据点
    if (step > 1 && sensorDataList.isNotEmpty) {
      final lastData = sensorDataList.last;
      if (spots.last.x != lastData.timestamp.millisecondsSinceEpoch.toDouble()) {
        spots.add(FlSpot(
          lastData.timestamp.millisecondsSinceEpoch.toDouble(),
          lastData.value,
        ));
      }
    }
    
    return spots;
  }

  // 计算最优时间间隔
  double? _calculateOptimalTimeInterval() {
    if (widget.sensorData.length < 2) return null;
    
    final sortedData = List<SensorData>.from(widget.sensorData)
      ..sort((a, b) => a.timestamp.compareTo(b.timestamp));
    
    final totalDuration = sortedData.last.timestamp.millisecondsSinceEpoch - 
                         sortedData.first.timestamp.millisecondsSinceEpoch;
    
    // 小图表显示2-3个时间标签
    const targetLabels = 2;
    return totalDuration / targetLabels;
  }

  // 计算最优数值间隔
  double? _calculateOptimalValueInterval() {
    if (widget.sensorData.isEmpty) return null;
    
    double minValue = widget.sensorData.first.value;
    double maxValue = widget.sensorData.first.value;
    
    for (var data in widget.sensorData) {
      minValue = minValue < data.value ? minValue : data.value;
      maxValue = maxValue > data.value ? maxValue : data.value;
    }
    
    final range = maxValue - minValue;
    if (range == 0) return null;
    
    // 小图表显示2-3个数值标签
    const targetLabels = 2;
    return range / targetLabels;
  }

  // 格式化坐标轴数值
  String _formatAxisValue(double value) {
    if (value.abs() >= 1000) {
      return '${(value / 1000).toStringAsFixed(1)}k';
    } else if (value.abs() >= 100) {
      return value.toStringAsFixed(0);
    } else {
      return value.toStringAsFixed(1);
    }
  }

  // 优化的工具提示构建方法
  List<LineTooltipItem> _buildTooltipItems(List<LineBarSpot> touchedBarSpots) {
    return touchedBarSpots.map((barSpot) {
      final timestamp = DateTime.fromMillisecondsSinceEpoch(barSpot.x.toInt());
      
      // 找到最接近的数据点
      final targetTime = barSpot.x.toInt();
      var closestData = widget.sensorData.first;
      var minDiff = (closestData.timestamp.millisecondsSinceEpoch - targetTime).abs();
      
      for (var data in widget.sensorData) {
        final diff = (data.timestamp.millisecondsSinceEpoch - targetTime).abs();
        if (diff < minDiff) {
          minDiff = diff;
          closestData = data;
        }
      }
      
      return LineTooltipItem(
        '${barSpot.y.toStringAsFixed(2)} ${closestData.unit}\n${DateFormat('HH:mm:ss').format(timestamp)}',
        const TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.bold,
          fontSize: 10,
        ),
      );
    }).toList();
  }

  Color _getSensorColor(String deviceType) {
    switch (deviceType.toUpperCase()) {
      case 'PH':
        return Colors.blue.shade600;
      case 'PH_TEMP':
        return Colors.purple.shade600;
      case 'TEMP':
      case 'PT100':
        return Colors.orange.shade600;
      case 'DDL':
        return Colors.amber.shade700;
      default:
        return Colors.grey.shade600;
    }
  }
}
