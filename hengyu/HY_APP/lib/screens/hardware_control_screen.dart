import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/valve_control_provider.dart';
import '../providers/sensor_provider.dart';
import '../services/api_service.dart';

class HardwareControlScreen extends StatefulWidget {
  const HardwareControlScreen({super.key});

  @override
  State<HardwareControlScreen> createState() => _HardwareControlScreenState();
}

class _HardwareControlScreenState extends State<HardwareControlScreen> {
  late ValveControlProvider _provider;
  final ApiService _apiService = ApiService();

  List<Map<String, dynamic>> _modeButtons = [];
  bool _loadingModes = true;
  String? _modeLoadError;
  bool _applyingMode = false;

  @override
  void initState() {
    super.initState();
    _provider = Provider.of<ValveControlProvider>(context, listen: false);
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      await _initializeProvider();
      await _loadModeUi();
    });
  }

  Future<void> _initializeProvider() async {
    try {
      await _provider.initialize();
    } catch (e) {
      debugPrint('Hardware control initialization error: $e');
    }
  }

  Future<void> _loadModeUi() async {
    if (!mounted) {
      return;
    }
    setState(() {
      _loadingModes = true;
      _modeLoadError = null;
    });
    final r = await _apiService.getModeUi();
    if (!mounted) {
      return;
    }
    if (r.success && r.data != null) {
      setState(() {
        _modeButtons = r.data!;
        _loadingModes = false;
      });
    } else {
      setState(() {
        _modeLoadError = r.message;
        _loadingModes = false;
      });
    }
  }

  Future<void> _onApplyMode(String mode) async {
    if (_applyingMode) {
      return;
    }
    setState(() => _applyingMode = true);
    final r = await _apiService.applyMode(mode);
    if (!mounted) {
      return;
    }
    setState(() => _applyingMode = false);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          r.success ? '已应用模式 $mode' : r.message,
        ),
        backgroundColor: r.success ? Colors.green.shade700 : Colors.red.shade700,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey.shade50,
      appBar: AppBar(
        title: const Text(
          '硬件控制',
          style: TextStyle(
            fontWeight: FontWeight.w600,
            color: Colors.white,
          ),
        ),
        backgroundColor: Colors.blue.shade700,
        foregroundColor: Colors.white,
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () async {
              await _provider.refreshStatus();
              await _loadModeUi();
            },
            tooltip: '刷新状态',
          ),
        ],
      ),
      body: Consumer2<ValveControlProvider, SensorProvider>(
        builder: (context, provider, sensorProvider, child) {
          final isAutoMode = sensorProvider.isAutoControlMode;

          return Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (isAutoMode)
                  Container(
                    margin: const EdgeInsets.only(bottom: 16),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.amber.shade100,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.amber.shade300),
                    ),
                    child: Row(
                      children: [
                        Icon(Icons.warning_amber_rounded, color: Colors.amber.shade800),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            '自动控制模式运行中 - 手动控制已禁用',
                            style: TextStyle(
                              color: Colors.amber.shade900,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),

                _buildStatusCard(provider),
                const SizedBox(height: 16),
                // Add Fan Status Card
                _buildFanStatusCard(sensorProvider),
                const SizedBox(height: 16),
                Expanded(
                  child: AbsorbPointer(
                    absorbing: isAutoMode,
                    child: Opacity(
                      opacity: isAutoMode ? 0.5 : 1.0,
                      child: ListView(
                        children: [
                          _buildModeButtonsSection(isAutoMode),
                          const SizedBox(height: 24),
                          _buildEmergencySection(provider),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildStatusCard(ValveControlProvider provider) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.info_outline,
                  color: Colors.blue.shade700,
                ),
                const SizedBox(width: 8),
                const Text(
                  '系统状态',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const Spacer(),
                if (provider.isLoading)
                  const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              provider.status,
              style: TextStyle(
                fontSize: 14,
                color: provider.errorMessage != null 
                    ? Colors.red.shade700 
                    : Colors.green.shade700,
                fontWeight: FontWeight.w500,
              ),
            ),
            if (provider.errorMessage != null) ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.red.shade50,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.red.shade200),
                ),
                child: Row(
                  children: [
                    Icon(
                      Icons.error_outline,
                      color: Colors.red.shade700,
                      size: 20,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        provider.errorMessage!,
                        style: TextStyle(
                          color: Colors.red.shade700,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildFanStatusCard(SensorProvider sensorProvider) {
    final fanSpeed = sensorProvider.fanSpeed;
    final isAlarming = sensorProvider.isAlarming;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.wind_power, color: Colors.blue.shade700),
                const SizedBox(width: 8),
                const Text(
                  '风扇与报警',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _buildInfoItem(
                    icon: Icons.cyclone,
                    label: '风扇转速',
                    value: '$fanSpeed',
                    valueColor: fanSpeed > 0 ? Colors.green.shade700 : Colors.grey,
                  ),
                ),
                Expanded(
                  child: _buildInfoItem(
                    icon: isAlarming ? Icons.warning : Icons.check_circle,
                    label: '报警状态',
                    value: isAlarming ? '报警中' : '正常',
                    valueColor: isAlarming ? Colors.red : Colors.green,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildInfoItem({
    required IconData icon,
    required String label,
    required String value,
    Color? valueColor,
  }) {
    return Column(
      children: [
        Icon(icon, color: valueColor ?? Colors.grey.shade700, size: 32),
        const SizedBox(height: 8),
        Text(
          label,
          style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.bold,
            color: valueColor ?? Colors.black87,
          ),
        ),
      ],
    );
  }

  Widget _buildModeButtonsSection(bool isAutoMode) {
    if (_loadingModes) {
      return const Padding(
        padding: EdgeInsets.all(24),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (_modeLoadError != null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            '加载模式按钮失败: $_modeLoadError',
            style: TextStyle(color: Colors.red.shade700),
          ),
        ),
      );
    }
    if (_modeButtons.isEmpty) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            '当前 script_define 未配置可见模式按钮',
            style: TextStyle(color: Colors.grey.shade700),
          ),
        ),
      );
    }
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '模式控制（script_define）',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: Colors.blue.shade800,
              ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: _modeButtons.map((row) {
                final mode = row['mode']?.toString() ?? '';
                final label = row['label']?.toString() ?? mode;
                return OutlinedButton(
                  onPressed: (isAutoMode || _applyingMode || mode.isEmpty)
                      ? null
                      : () => _onApplyMode(mode),
                  child: Text(label),
                );
              }).toList(),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmergencySection(ValveControlProvider provider) {
    return Card(
      color: Colors.red.shade50,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.warning,
                  color: Colors.red.shade700,
                ),
                const SizedBox(width: 8),
                Text(
                  '紧急控制',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                    color: Colors.red.shade700,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              '紧急情况下可以快速关闭所有阀门和光源',
              style: TextStyle(
                fontSize: 12,
                color: Colors.red.shade600,
              ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: provider.isLoading ? null : () => _showEmergencyConfirmDialog(provider),
                icon: const Icon(Icons.power_settings_new),
                label: const Text(
                  '关闭所有设备',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.red.shade600,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 12),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _showEmergencyConfirmDialog(ValveControlProvider provider) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Row(
          children: [
            Icon(
              Icons.warning,
              color: Colors.red.shade700,
            ),
            const SizedBox(width: 8),
            const Text('确认紧急关闭'),
          ],
        ),
        content: const Text('确定要关闭所有阀门和光源吗？此操作不可撤销。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('取消'),
          ),
          ElevatedButton(
            onPressed: () async {
              Navigator.of(context).pop();
              await provider.turnOffAll();
              // Check if widget is still mounted before showing snackbar
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(
                      provider.errorMessage ?? '所有设备已关闭',
                    ),
                    backgroundColor: provider.errorMessage != null 
                        ? Colors.red 
                        : Colors.green,
                  ),
                );
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.red.shade600,
              foregroundColor: Colors.white,
            ),
            child: const Text('确认关闭'),
          ),
        ],
      ),
    );
  }
}
