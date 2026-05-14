import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../models/sensor_data.dart';
import 'single_sensor_chart.dart';

class SensorDataWidget extends StatefulWidget {
  final Map<String, SensorData> sensorData;
  final Map<String, List<SensorData>> historicalData;
  final bool isCollecting;
  final String status;

  // ---- 桥接（hy_server.BridgeDataManager）字段 ----
  final double? bridgeTemperature;
  final double? bridgeLevel;
  final String? bridgeState;
  final String? bridgeError;
  final DateTime? bridgeLastUpdateTs;
  final bool bridgeConnected;
  /// `/hy-device/sensors` 是否曾成功响应。即便桥接线程尚未上送数据，
  /// 只要后端可达，也会显示桥接温度/液位卡片以便看到断连状态。
  final bool bridgeAvailable;

  const SensorDataWidget({
    super.key,
    required this.sensorData,
    required this.historicalData,
    required this.isCollecting,
    required this.status,
    this.bridgeTemperature,
    this.bridgeLevel,
    this.bridgeState,
    this.bridgeError,
    this.bridgeLastUpdateTs,
    this.bridgeConnected = false,
    this.bridgeAvailable = false,
  });

  @override
  State<SensorDataWidget> createState() => _SensorDataWidgetState();
}

class _SensorDataWidgetState extends State<SensorDataWidget> {
  @override
  Widget build(BuildContext context) {
    // 添加调试信息
    print('🔍 SensorDataWidget build - sensorData有${widget.sensorData.length}个传感器');
    for (final entry in widget.sensorData.entries) {
      print('  ${entry.key}: ${entry.value.value} ${entry.value.unit} (${entry.value.timestamp})');
    }
    print('🔍 SensorDataWidget build - historicalData有${widget.historicalData.length}个传感器');
    for (final entry in widget.historicalData.entries) {
      print('  ${entry.key}: ${entry.value.length}个历史数据点');
    }
    
    return Column(
      children: [
        // Current values section with embedded charts
        Container(
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
              _buildSensorGrid(),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildHeader() {
    return Row(
      children: [
        Icon(
          Icons.sensors,
          color: Colors.green.shade700,
        ),
        const SizedBox(width: 8),
        const Text(
          '传感器数据',
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            color: Colors.black87,
          ),
        ),
        const Spacer(),
        if (widget.isCollecting)
          Row(
            children: [
              SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.green.shade600),
                ),
              ),
              const SizedBox(width: 8),
              Text(
                '数据采集中...',
                style: TextStyle(
                  fontSize: 12,
                  color: Colors.green.shade600,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ],
          )
        else
          Text(
            widget.status,
            style: TextStyle(
              fontSize: 12,
              color: Colors.grey.shade600,
            ),
          ),
      ],
    );
  }

  Widget _buildSensorGrid() {
    // 只要后端 /hy-device/sensors 接口曾成功响应过，就显示桥接卡片：
    // 这样即便桥接线程暂时离线，也能直观显示"桥接异常"而不是隐藏卡片。
    final hasBridge = widget.bridgeAvailable;

    if (widget.sensorData.isEmpty && !hasBridge) {
      return Container(
        height: 120,
        width: double.infinity,
        decoration: BoxDecoration(
          color: Colors.grey.shade50,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.grey.shade200),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.sensors_off,
              size: 32,
              color: Colors.grey.shade400,
            ),
            const SizedBox(height: 8),
            Text(
              '无传感器数据',
              style: TextStyle(
                color: Colors.grey.shade600,
                fontSize: 14,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              '连接设备并开始采集数据',
              style: TextStyle(
                color: Colors.grey.shade500,
                fontSize: 12,
              ),
            ),
          ],
        ),
      );
    }

    final cards = <Widget>[
      ...widget.sensorData.entries.map((entry) {
        return Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: _buildSensorCard(entry.key, entry.value),
        );
      }),
    ];
    if (hasBridge) {
      cards.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: _buildBridgeCard(
            label: '桥接温度',
            value: widget.bridgeTemperature ?? 0.0,
            unit: '°C',
            icon: Icons.whatshot_outlined,
            color: _bridgeTempColor(widget.bridgeTemperature ?? 0.0),
          ),
        ),
      );
      cards.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: _buildBridgeCard(
            label: '液位',
            value: widget.bridgeLevel ?? 0.0,
            unit: '',
            icon: Icons.water_drop_outlined,
            color: Colors.cyan.shade700,
            decimals: 4,
          ),
        ),
      );
    }
    return Column(children: cards);
  }

  Color _bridgeTempColor(double v) {
    if (v > 85) return Colors.red.shade600;
    if (v > 45) return Colors.deepOrange.shade600;
    return Colors.green.shade700;
  }

  /// 桥接（hy_server.BridgeDataManager）专用卡片：与传感器卡片样式保持一致，
  /// 但右侧显示"状态徽标"而非趋势图，因为桥接数据未做历史曲线缓存。
  Widget _buildBridgeCard({
    required String label,
    required double value,
    required String unit,
    required IconData icon,
    required Color color,
    int decimals = 2,
  }) {
    final hasError = widget.bridgeError != null && widget.bridgeError!.isNotEmpty;
    final stateLabel = (widget.bridgeState ?? 'reset') == 'triggered' ? '已触发' : '待机';
    final ts = widget.bridgeLastUpdateTs;

    return Container(
      height: 120,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.grey.shade300),
        boxShadow: [
          BoxShadow(
            color: Colors.grey.shade200,
            blurRadius: 2,
            offset: const Offset(0, 1),
          ),
        ],
      ),
      child: Row(
        children: [
          Expanded(
            flex: 2,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    Icon(icon, size: 16, color: color),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        label,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: Colors.black87,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.baseline,
                      textBaseline: TextBaseline.alphabetic,
                      children: [
                        Text(
                          value.toStringAsFixed(decimals),
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.bold,
                            color: hasError ? Colors.grey.shade500 : color,
                          ),
                        ),
                        if (unit.isNotEmpty) ...[
                          const SizedBox(width: 4),
                          Text(
                            unit,
                            style: const TextStyle(
                              fontSize: 12,
                              color: Colors.black54,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      ts != null ? DateFormat('HH:mm:ss').format(ts) : '—',
                      style: TextStyle(
                        fontSize: 10,
                        color: Colors.grey.shade600,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            flex: 3,
            child: Container(
              height: 96,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.grey.shade50,
                borderRadius: BorderRadius.circular(4),
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                        widget.bridgeConnected
                            ? Icons.cable
                            : Icons.power_off_outlined,
                        size: 14,
                        color: widget.bridgeConnected
                            ? Colors.green.shade600
                            : Colors.red.shade500,
                      ),
                      const SizedBox(width: 6),
                      Text(
                        widget.bridgeConnected ? '桥接正常' : '桥接异常',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: widget.bridgeConnected
                              ? Colors.green.shade700
                              : Colors.red.shade600,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '状态：$stateLabel',
                    style: TextStyle(
                      fontSize: 11,
                      color: Colors.grey.shade700,
                    ),
                  ),
                  if (hasError) ...[
                    const SizedBox(height: 4),
                    Text(
                      widget.bridgeError!,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 10,
                        color: Colors.red.shade600,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSensorCard(String deviceType, SensorData data) {
    // 获取该传感器的历史数据
    final historicalData = widget.historicalData[deviceType] ?? [];
    
    return Container(
      height: 120, // 固定较小的高度
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.grey.shade300),
        boxShadow: [
          BoxShadow(
            color: Colors.grey.shade200,
            blurRadius: 2,
            offset: const Offset(0, 1),
          ),
        ],
      ),
      child: Row(
        children: [
          // 左侧：传感器信息和当前值
          Expanded(
            flex: 2,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                // 传感器标题
                Row(
                  children: [
                    _getDeviceIcon(deviceType),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _getDeviceDisplayName(deviceType),
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: Colors.black87,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                
                // 当前值显示
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.baseline,
                      textBaseline: TextBaseline.alphabetic,
                      children: [
                        Text(
                          _formatValue(data.value),
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.bold,
                            color: _getValueColor(deviceType, data.value),
                          ),
                        ),
                        const SizedBox(width: 4),
                        Text(
                          data.unit,
                          style: const TextStyle(
                            fontSize: 12,
                            color: Colors.black54,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      DateFormat('HH:mm:ss').format(data.timestamp),
                      style: TextStyle(
                        fontSize: 10,
                        color: Colors.grey.shade600,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          
          const SizedBox(width: 16),
          
          // 右侧：图表区域填充剩余空间
          Expanded(
            flex: 3,
            child: historicalData.isNotEmpty 
                ? SingleSensorChart(
                    sensorType: deviceType,
                    sensorData: historicalData,
                    height: 96, // 使用卡片高度减去padding
                  )
                : Container(
                    height: 96,
                    decoration: BoxDecoration(
                      color: Colors.grey.shade50,
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Center(
                      child: Text(
                        '无趋势数据',
                        style: TextStyle(
                          fontSize: 11,
                          color: Colors.grey.shade500,
                        ),
                      ),
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _getDeviceIcon(String deviceType) {
    switch (deviceType.toUpperCase()) {
      case 'PH':
        return Icon(
          Icons.water_drop,
          size: 16,
          color: Colors.blue.shade600,
        );
      case 'PH_TEMP':
        return Icon(
          Icons.device_thermostat,
          size: 16,
          color: Colors.purple.shade600,
        );
      case 'TEMP':
      case 'PT100':
        return Icon(
          Icons.thermostat,
          size: 16,
          color: Colors.orange.shade600,
        );
      case 'DDL':
        return Icon(
          Icons.electric_bolt,
          size: 16,
          color: Colors.amber.shade700,
        );
      default:
        return Icon(
          Icons.sensors,
          size: 16,
          color: Colors.grey.shade600,
        );
    }
  }

  String _getDeviceDisplayName(String deviceType) {
    switch (deviceType.toUpperCase()) {
      case 'PH':
        return 'pH值';
      case 'PH_TEMP':
        return 'pH温度';
      case 'TEMP':
        return '温度';
      case 'PT100':
        return 'PT100温度';
      case 'DDL':
        return '电导率';
      default:
        return deviceType.toUpperCase();
    }
  }

  String _formatValue(double value) {
    if (value.abs() >= 1000) {
      return value.toStringAsFixed(0);
    } else if (value.abs() >= 100) {
      return value.toStringAsFixed(1);
    } else {
      return value.toStringAsFixed(2);
    }
  }

  Color _getValueColor(String deviceType, double value) {
    switch (deviceType.toUpperCase()) {
      case 'PH':
        if (value < 6.5 || value > 8.5) {
          return Colors.red.shade600; // Outside normal pH range
        }
        return Colors.blue.shade600;
      case 'PH_TEMP':
      case 'TEMP':
      case 'PT100':
        if (value < 0 || value > 50) {
          return Colors.orange.shade700; // Extreme temperature
        }
        return Colors.orange.shade600;
      case 'DDL':
        if (value < 50 || value > 2000) {
          return Colors.red.shade600; // Abnormal conductivity range
        }
        return Colors.amber.shade700;
      default:
        return Colors.black87;
    }
  }
}
