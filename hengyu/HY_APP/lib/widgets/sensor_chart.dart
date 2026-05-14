import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:intl/intl.dart';
import '../models/sensor_data.dart';

class SensorChart extends StatefulWidget {
  final Map<String, List<SensorData>> historicalData;
  final double height;

  const SensorChart({
    super.key,
    required this.historicalData,
    this.height = 300,
  });

  @override
  State<SensorChart> createState() => _SensorChartState();
}

class _SensorChartState extends State<SensorChart> {
  String? _selectedSensorType;
  bool _showAllSensors = true;
  final Map<String, bool> _sensorVisibility = {};
  
  // 缓存优化
  Map<String, List<FlSpot>>? _cachedSpots;
  List<LineChartBarData>? _cachedLines;
  int _lastDataHash = 0;

  @override
  void initState() {
    super.initState();
    // Initialize visibility for all sensor types
    for (String sensorType in widget.historicalData.keys) {
      _sensorVisibility[sensorType] = true;
    }
  }

  @override
  void didUpdateWidget(SensorChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 检查数据是否变化，如果变化则清除缓存
    final newDataHash = _calculateDataHash();
    if (newDataHash != _lastDataHash) {
      _cachedSpots = null;
      _cachedLines = null;
      _lastDataHash = newDataHash;
    }
  }

  // 计算数据哈希值用于缓存比较
  int _calculateDataHash() {
    int hash = 0;
    for (var entry in widget.historicalData.entries) {
      hash ^= entry.key.hashCode;
      hash ^= entry.value.length.hashCode;
      if (entry.value.isNotEmpty) {
        hash ^= entry.value.last.timestamp.millisecondsSinceEpoch.hashCode;
      }
    }
    return hash;
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      height: widget.height,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: Colors.grey.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildHeader(),
          const SizedBox(height: 16),
          _buildControls(),
          const SizedBox(height: 16),
          Expanded(child: _buildChart()),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return Row(
      children: [
        Icon(
          Icons.timeline,
          color: Colors.blue.shade700,
          size: 20,
        ),
        const SizedBox(width: 8),
        const Text(
          '传感器趋势',
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            color: Colors.black87,
          ),
        ),
        const Spacer(),
        Text(
          '${widget.historicalData.keys.length} sensors',
          style: TextStyle(
            fontSize: 12,
            color: Colors.grey.shade600,
          ),
        ),
      ],
    );
  }

  Widget _buildControls() {
    return Column(
      children: [
        // Sensor type filter
        Row(
          children: [
            const Text(
              '视图: ',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w500,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Wrap(
                spacing: 8,
                children: [
                  FilterChip(
                    label: const Text('全部'),
                    selected: _showAllSensors,
                    onSelected: _onAllSensorsToggle,
                  ),
                  ...widget.historicalData.keys.map((sensorType) => FilterChip(
                    label: Text(_getSensorDisplayName(sensorType)),
                    selected: !_showAllSensors && _selectedSensorType == sensorType,
                    onSelected: (selected) => _onSingleSensorToggle(sensorType, selected),
                  )),
                ],
              ),
            ),
          ],
        ),
        // Individual sensor toggles when showing all
        if (_showAllSensors) ...[
          const SizedBox(height: 8),
          Row(
            children: [
              const Text(
                '显示: ',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Wrap(
                  spacing: 8,
                  children: widget.historicalData.keys.map((sensorType) => FilterChip(
                    label: Text(_getSensorDisplayName(sensorType)),
                    selected: _sensorVisibility[sensorType] ?? false,
                    selectedColor: _getSensorColor(sensorType).withOpacity(0.2),
                    onSelected: (selected) => _onIndividualSensorToggle(sensorType, selected),
                  )).toList(),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }

  // 优化的事件处理方法，减少不必要的重建
  void _onAllSensorsToggle(bool selected) {
    if (selected == _showAllSensors) return;
    
    setState(() {
      _showAllSensors = selected;
      if (selected) {
        _selectedSensorType = null;
        for (String key in _sensorVisibility.keys) {
          _sensorVisibility[key] = true;
        }
        // 清除缓存以强制重建图表
        _cachedLines = null;
      }
    });
  }

  void _onSingleSensorToggle(String sensorType, bool selected) {
    if (!selected && _selectedSensorType == sensorType) return;
    if (selected && _selectedSensorType == sensorType && !_showAllSensors) return;
    
    setState(() {
      _showAllSensors = false;
      _selectedSensorType = selected ? sensorType : null;
      // Update visibility
      for (String key in _sensorVisibility.keys) {
        _sensorVisibility[key] = selected ? key == sensorType : false;
      }
      // 清除缓存以强制重建图表
      _cachedLines = null;
    });
  }

  void _onIndividualSensorToggle(String sensorType, bool selected) {
    if ((_sensorVisibility[sensorType] ?? false) == selected) return;
    
    setState(() {
      _sensorVisibility[sensorType] = selected;
      // 只需要清除缓存的线条数据，数据点可以保留
      _cachedLines = null;
    });
  }

  Widget _buildChart() {
    if (widget.historicalData.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.timeline_outlined,
              size: 48,
              color: Colors.grey.shade400,
            ),
            const SizedBox(height: 16),
            Text(
              '无历史数据',
              style: TextStyle(
                fontSize: 16,
                color: Colors.grey.shade600,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '开始采集传感器数据以查看趋势',
              style: TextStyle(
                fontSize: 12,
                color: Colors.grey.shade500,
              ),
            ),
          ],
        ),
      );
    }

    // 使用缓存的线条数据或重新构建
    final lines = _buildOptimizedLines();

    if (lines.isEmpty) {
      return Center(
        child: Text(
          '请选择至少一个传感器进行显示',
          style: TextStyle(
            fontSize: 14,
            color: Colors.grey.shade600,
          ),
        ),
      );
    }

    return LineChart(
      LineChartData(
        lineBarsData: lines,
        titlesData: _buildOptimizedTitles(),
        gridData: FlGridData(
          show: true,
          drawVerticalLine: true,
          horizontalInterval: null,
          verticalInterval: null,
          getDrawingHorizontalLine: (value) {
            return FlLine(
              color: Colors.grey.shade300,
              strokeWidth: 1,
            );
          },
          getDrawingVerticalLine: (value) {
            return FlLine(
              color: Colors.grey.shade300,
              strokeWidth: 1,
            );
          },
        ),
        borderData: FlBorderData(
          show: true,
          border: Border.all(color: Colors.grey.shade300),
        ),
        lineTouchData: LineTouchData(
          enabled: true,
          touchCallback: (FlTouchEvent event, LineTouchResponse? touchResponse) {
            // 优化触摸响应，减少不必要的重绘
          },
          touchTooltipData: LineTouchTooltipData(
            getTooltipItems: _buildTooltipItems,
          ),
        ),
        // 性能优化设置
        clipData: const FlClipData.all(),
        backgroundColor: Colors.transparent,
      ),
    );
  }

  // 优化的线条构建方法
  List<LineChartBarData> _buildOptimizedLines() {
    // 检查是否可以使用缓存
    if (_cachedLines != null && _canUseCachedLines()) {
      return _cachedLines!.where((line) {
        final sensorType = _getSensorTypeFromColor(line.color);
        return _sensorVisibility[sensorType] == true;
      }).toList();
    }

    final lines = <LineChartBarData>[];
    
    for (String sensorType in widget.historicalData.keys) {
      if (_sensorVisibility[sensorType] == true) {
        final spots = _getCachedSpots(sensorType);
        if (spots.isNotEmpty) {
          lines.add(LineChartBarData(
            spots: spots,
            color: _getSensorColor(sensorType),
            barWidth: 2,
            isStrokeCapRound: true,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(show: false),
            // 性能优化设置
            preventCurveOverShooting: true,
            preventCurveOvershootingThreshold: 10,
          ));
        }
      }
    }

    // 缓存结果
    _cachedLines = List.from(lines);
    return lines;
  }

  // 优化的标题构建方法
  FlTitlesData _buildOptimizedTitles() {
    return FlTitlesData(
      rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
      topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
      bottomTitles: AxisTitles(
        sideTitles: SideTitles(
          showTitles: true,
          reservedSize: 30,
          interval: _calculateOptimalTimeInterval(),
          getTitlesWidget: (value, meta) {
            final timestamp = DateTime.fromMillisecondsSinceEpoch(value.toInt());
            return SideTitleWidget(
              axisSide: meta.axisSide,
              child: Text(
                DateFormat('HH:mm').format(timestamp),
                style: const TextStyle(
                  color: Colors.grey,
                  fontSize: 10,
                ),
              ),
            );
          },
        ),
      ),
      leftTitles: AxisTitles(
        sideTitles: SideTitles(
          showTitles: true,
          reservedSize: 40,
          interval: _calculateOptimalValueInterval(),
          getTitlesWidget: (value, meta) {
            return SideTitleWidget(
              axisSide: meta.axisSide,
              child: Text(
                value.toStringAsFixed(1),
                style: const TextStyle(
                  color: Colors.grey,
                  fontSize: 10,
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  // 获取缓存的数据点
  List<FlSpot> _getCachedSpots(String sensorType) {
    _cachedSpots ??= {};
    
    if (!_cachedSpots!.containsKey(sensorType)) {
      _cachedSpots![sensorType] = _createOptimizedSpots(widget.historicalData[sensorType]!);
    }
    
    return _cachedSpots![sensorType]!;
  }

  // 优化的数据点创建方法
  List<FlSpot> _createOptimizedSpots(List<SensorData> sensorDataList) {
    if (sensorDataList.isEmpty) return [];
    
    // 如果数据点太多，进行采样以提高性能
    final maxPoints = 50; // 最大显示点数
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

  // 检查是否可以使用缓存的线条
  bool _canUseCachedLines() {
    return _cachedLines != null && _cachedLines!.isNotEmpty;
  }

  // 从颜色获取传感器类型
  String _getSensorTypeFromColor(Color? color) {
    if (color == null) return '';
    
    for (String sensorType in widget.historicalData.keys) {
      if (_getSensorColor(sensorType) == color) {
        return sensorType;
      }
    }
    return '';
  }

  // 计算最优时间间隔
  double? _calculateOptimalTimeInterval() {
    if (widget.historicalData.isEmpty) return null;
    
    final allData = widget.historicalData.values.expand((list) => list).toList();
    if (allData.length < 2) return null;
    
    allData.sort((a, b) => a.timestamp.compareTo(b.timestamp));
    final totalDuration = allData.last.timestamp.millisecondsSinceEpoch - 
                         allData.first.timestamp.millisecondsSinceEpoch;
    
    // 根据总时长计算合适的间隔
    const targetLabels = 5;
    return totalDuration / targetLabels;
  }

  // 计算最优数值间隔
  double? _calculateOptimalValueInterval() {
    if (widget.historicalData.isEmpty) return null;
    
    double minValue = double.infinity;
    double maxValue = double.negativeInfinity;
    
    for (var sensorData in widget.historicalData.values) {
      for (var data in sensorData) {
        if (_sensorVisibility[data.deviceType] == true) {
          minValue = minValue < data.value ? minValue : data.value;
          maxValue = maxValue > data.value ? maxValue : data.value;
        }
      }
    }
    
    if (minValue == double.infinity) return null;
    
    final range = maxValue - minValue;
    const targetLabels = 5;
    return range / targetLabels;
  }

  // 优化的工具提示构建方法
  List<LineTooltipItem> _buildTooltipItems(List<LineBarSpot> touchedBarSpots) {
    return touchedBarSpots.map((barSpot) {
      final sensorType = _getSensorTypeFromColor(barSpot.bar.color);
      final timestamp = DateTime.fromMillisecondsSinceEpoch(barSpot.x.toInt());
      
      // 使用缓存查找对应的传感器数据
      final sensorDataList = widget.historicalData[sensorType];
      if (sensorDataList == null || sensorDataList.isEmpty) {
        return LineTooltipItem('', const TextStyle());
      }
      
      // 找到最接近的数据点
      final targetTime = barSpot.x.toInt();
      var closestData = sensorDataList.first;
      var minDiff = (closestData.timestamp.millisecondsSinceEpoch - targetTime).abs();
      
      for (var data in sensorDataList) {
        final diff = (data.timestamp.millisecondsSinceEpoch - targetTime).abs();
        if (diff < minDiff) {
          minDiff = diff;
          closestData = data;
        }
      }
      
      return LineTooltipItem(
        '${_getSensorDisplayName(sensorType)}\n${barSpot.y.toStringAsFixed(2)} ${closestData.unit}\n${DateFormat('HH:mm:ss').format(timestamp)}',
        const TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.bold,
          fontSize: 12,
        ),
      );
    }).toList();
  }

  String _getSensorDisplayName(String deviceType) {
    switch (deviceType.toUpperCase()) {
      case 'PH':
        return 'pH值';
      case 'PH_TEMP':
        return 'pH温度';
      case 'TEMP':
        return '温度';
      case 'PT100':
        return 'PT100';
      case 'DDL':
        return '电导率';
      default:
        return deviceType.toUpperCase();
    }
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
