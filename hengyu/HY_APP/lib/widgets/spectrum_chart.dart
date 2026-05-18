import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../models/spectrum_data.dart';

class SpectrumChart extends StatefulWidget {
  final SpectrumData? spectrumData;
  final double height;

  const SpectrumChart({
    super.key,
    this.spectrumData,
    this.height = 300,
  });

  @override
  State<SpectrumChart> createState() => _SpectrumChartState();
}

class _SpectrumChartState extends State<SpectrumChart> {
  bool _showGrid = true;
  bool _autoScale = true;
  double _minY = 0;
  double _maxY = 65535;

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
        children: [
          _buildControls(),
          const SizedBox(height: 12),
          Expanded(child: _buildChart()),
        ],
      ),
    );
  }

  Widget _buildControls() {
    return Row(
      children: [
        Icon(Icons.timeline, color: Colors.blue.shade700),
        const SizedBox(width: 8),
        const Text(
          '光谱',
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            color: Colors.black87,
          ),
        ),
        const Spacer(),
        Row(
          children: [
            InkWell(
              onTap: () {
                setState(() {
                  _showGrid = !_showGrid;
                });
              },
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: _showGrid ? Colors.blue.shade50 : Colors.grey.shade100,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.grid_on,
                      size: 14,
                      color: _showGrid ? Colors.blue : Colors.grey,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '网格',
                      style: TextStyle(
                        fontSize: 12,
                        color: _showGrid ? Colors.blue : Colors.grey,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 8),
            InkWell(
              onTap: () {
                setState(() {
                  _autoScale = !_autoScale;
                  if (_autoScale && widget.spectrumData != null) {
                    _updateAutoScale();
                  }
                });
              },
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: _autoScale ? Colors.green.shade50 : Colors.grey.shade100,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.auto_fix_high,
                      size: 14,
                      color: _autoScale ? Colors.green : Colors.grey,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '自动',
                      style: TextStyle(
                        fontSize: 12,
                        color: _autoScale ? Colors.green : Colors.grey,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildChart() {
    if (widget.spectrumData == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.timeline,
              size: 48,
              color: Colors.grey.shade400,
            ),
            const SizedBox(height: 12),
            Text(
              '无光谱数据',
              style: TextStyle(
                color: Colors.grey.shade600,
                fontSize: 16,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '开始数据采集以查看光谱',
              style: TextStyle(
                color: Colors.grey.shade500,
                fontSize: 14,
              ),
            ),
          ],
        ),
      );
    }

    final spectrumData = widget.spectrumData!;
    
    if (_autoScale) {
      _updateAutoScale();
    }

    final spots = _createSpots(spectrumData);

    return LineChart(
      LineChartData(
        gridData: FlGridData(
          show: _showGrid,
          drawVerticalLine: true,
          drawHorizontalLine: true,
          horizontalInterval: (_maxY - _minY) / 5,
          getDrawingHorizontalLine: (value) {
            return FlLine(
              color: Colors.grey.shade300,
              strokeWidth: 0.5,
            );
          },
          getDrawingVerticalLine: (value) {
            return FlLine(
              color: Colors.grey.shade300,
              strokeWidth: 0.5,
            );
          },
        ),
        titlesData: FlTitlesData(
          show: true,
          rightTitles: const AxisTitles(
            sideTitles: SideTitles(showTitles: false),
          ),
          topTitles: const AxisTitles(
            sideTitles: SideTitles(showTitles: false),
          ),
          bottomTitles: AxisTitles(
            axisNameWidget: const Text(
              '波长 (nm)',
              style: TextStyle(
                fontSize: 12,
                color: Colors.black87,
                fontWeight: FontWeight.w500,
              ),
            ),
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 30,
              interval: 100,
              getTitlesWidget: (value, meta) {
                return SideTitleWidget(
                  axisSide: meta.axisSide,
                  child: Text(
                    value.toInt().toString(),
                    style: const TextStyle(
                      fontSize: 10,
                      color: Colors.black87,
                    ),
                  ),
                );
              },
            ),
          ),
          leftTitles: AxisTitles(
            axisNameWidget: const Text(
              '强度',
              style: TextStyle(
                fontSize: 12,
                color: Colors.black87,
                fontWeight: FontWeight.w500,
              ),
            ),
            sideTitles: SideTitles(
              showTitles: true,
              interval: (_maxY - _minY) / 4,
              reservedSize: 60,
              getTitlesWidget: (value, meta) {
                return SideTitleWidget(
                  axisSide: meta.axisSide,
                  child: Text(
                    _formatIntensity(value),
                    style: const TextStyle(
                      fontSize: 10,
                      color: Colors.black87,
                    ),
                  ),
                );
              },
            ),
          ),
        ),
        borderData: FlBorderData(
          show: true,
          border: Border.all(color: Colors.grey.shade300, width: 1),
        ),
        minX: SpectrumData.acquisitionWavelengthMinNm.toDouble(),
        maxX: SpectrumData.acquisitionWavelengthMaxNm.toDouble(),
        minY: _minY,
        maxY: _maxY,
        lineBarsData: [
          LineChartBarData(
            spots: spots,
            isCurved: false,
            color: Colors.blue.shade600,
            barWidth: 1,
            isStrokeCapRound: false,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(
              show: true,
              color: Colors.blue.shade100.withOpacity(0.3),
            ),
          ),
        ],
        lineTouchData: LineTouchData(
          enabled: true,
          touchTooltipData: LineTouchTooltipData(
            getTooltipColor: (touchedSpot) => Colors.black87,
            getTooltipItems: (List<LineBarSpot> touchedBarSpots) {
              return touchedBarSpots.map((barSpot) {
                return LineTooltipItem(
                  'λ: ${barSpot.x.toStringAsFixed(1)} nm\nI: ${barSpot.y.toStringAsFixed(0)}',
                  const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                  ),
                );
              }).toList();
            },
          ),
        ),
      ),
    );
  }

  List<FlSpot> _createSpots(SpectrumData spectrumData) {
    final spots = <FlSpot>[];
    for (var i = 0; i < spectrumData.intensities.length; i++) {
      spots.add(FlSpot(
        spectrumData.wavelengthAt(i),
        spectrumData.intensities[i].toDouble(),
      ));
    }
    return spots;
  }

  void _updateAutoScale() {
    if (widget.spectrumData != null) {
      final intensities = widget.spectrumData!.intensities;
      if (intensities.isNotEmpty) {
        final minIntensity = intensities.reduce((a, b) => a < b ? a : b).toDouble();
        final maxIntensity = intensities.reduce((a, b) => a > b ? a : b).toDouble();
        
        final padding = (maxIntensity - minIntensity) * 0.1;
        _minY = (minIntensity - padding).clamp(0, double.infinity);
        _maxY = maxIntensity + padding;
      }
    }
  }

  String _formatIntensity(double value) {
    if (value >= 1000) {
      return '${(value / 1000).toStringAsFixed(1)}k';
    } else {
      return value.toInt().toString();
    }
  }
}
