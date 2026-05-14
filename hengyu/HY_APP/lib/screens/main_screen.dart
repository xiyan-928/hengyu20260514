import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/spectrum_provider.dart';
import '../providers/sensor_provider.dart';
import '../widgets/spectrum_chart.dart';
import '../widgets/sensor_data_widget.dart';
import 'settings_screen.dart';

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  bool _isInitialized = false;

  @override
  void initState() {
    super.initState();
    _initializeApp();
  }

  Future<void> _initializeApp() async {
    final spectrumProvider = Provider.of<SpectrumProvider>(context, listen: false);
    final sensorProvider = Provider.of<SensorProvider>(context, listen: false);

    // Load user settings first
    await spectrumProvider.initialize();

    // Initialize CDS350
    await spectrumProvider.initializeDevice();

    // Initialize sensors with fetched settings
    print('🔍 MainScreen: 开始初始化传感器...');
    final apiService = ApiService();
    try {
      final settingsResponse = await apiService.getDeviceSettings();
      if (settingsResponse.success && settingsResponse.data != null) {
        final ip = settingsResponse.data!.ip;
        final port = settingsResponse.data!.port;
        final sensorSuccess = await sensorProvider.initializeSensors(ip, port);
        print('🔍 MainScreen: 传感器初始化结果: $sensorSuccess');
      } else {
        print('🔍 MainScreen: 获取设置失败: ${settingsResponse.message}');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('初始化失败: 无法获取设备配置 (${settingsResponse.message})')),
          );
        }
      }
    } catch (e) {
      print('🔍 MainScreen: 初始化异常: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('初始化异常: $e')),
        );
      }
    }
    print('🔍 MainScreen: 可用设备类型: ${sensorProvider.availableDeviceTypes}');
    print('🔍 MainScreen: 当前状态: ${sensorProvider.status}');

    setState(() {
      _isInitialized = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey.shade50,
      appBar: AppBar(
        title: const Text(
          'HY 数据采集系统',
          style: TextStyle(
            fontWeight: FontWeight.w600,
            color: Colors.white,
          ),
        ),
        backgroundColor: Colors.blue.shade700,
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.settings, color: Colors.white),
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const SettingsScreen()),
              );
            },
          ),
          Consumer2<SpectrumProvider, SensorProvider>(
            builder: (context, spectrumProvider, sensorProvider, child) {
              return PopupMenuButton<String>(
                icon: const Icon(Icons.more_vert, color: Colors.white),
                onSelected: (value) => _handleMenuAction(value, spectrumProvider, sensorProvider),
                itemBuilder: (context) => [
                  const PopupMenuItem(
                    value: 'settings',
                    child: Row(
                      children: [
                        Icon(Icons.settings),
                        SizedBox(width: 8),
                        Text('设置'),
                      ],
                    ),
                  ),
                  const PopupMenuItem(
                    value: 'about',
                    child: Row(
                      children: [
                        Icon(Icons.info),
                        SizedBox(width: 8),
                        Text('关于'),
                      ],
                    ),
                  ),
                ],
              );
            },
          ),
        ],
      ),
      body: _isInitialized ? _buildMainContent() : _buildLoadingScreen(),
      floatingActionButton: _buildFloatingActionButton(),
    );
  }

  Widget _buildLoadingScreen() {
    return const Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          CircularProgressIndicator(),
          SizedBox(height: 16),
          Text(
            '设备初始化中...',
            style: TextStyle(
              fontSize: 16,
              color: Colors.black87,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMainContent() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          _buildControlPanel(),
          const SizedBox(height: 16),
          _buildSpectrumSection(),
          const SizedBox(height: 16),
          _buildSensorSection(),
        ],
      ),
    );
  }

  Widget _buildControlPanel() {
    return Consumer2<SpectrumProvider, SensorProvider>(
      builder: (context, spectrumProvider, sensorProvider, child) {
        return Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.grey.shade300),
          ),
          child: Column(
            children: [
              Row(
                children: [
                  const Icon(Icons.control_camera, color: Colors.blue),
                  const SizedBox(width: 8),
                  const Text(
                    '控制面板',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const Spacer(),
                  _buildStatusIndicator(spectrumProvider, sensorProvider),
                ],
              ),
              const SizedBox(height: 16),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: _buildSpectrumControls(spectrumProvider),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: _buildSensorControls(sensorProvider),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildStatusIndicator(SpectrumProvider spectrumProvider, SensorProvider sensorProvider) {
    final spectrumStatus = spectrumProvider.isInitialized;
    final sensorStatus = sensorProvider.isConnected;

    return Row(
      children: [
        _buildStatusDot('光谱仪', spectrumStatus),
        const SizedBox(width: 12),
        _buildStatusDot('传感器', sensorStatus),
      ],
    );
  }

  Widget _buildStatusDot(String label, bool isConnected) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            color: isConnected ? Colors.green : Colors.red,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 4),
        Text(
          label,
          style: TextStyle(
            fontSize: 12,
            color: Colors.grey.shade700,
          ),
        ),
      ],
    );
  }

  Widget _buildSpectrumControls(SpectrumProvider provider) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '光谱采集',
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w500,
          ),
        ),
        const SizedBox(height: 8),
        if (provider.isAutoControlMode)
          Container(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
            decoration: BoxDecoration(
              color: Colors.blue.shade50,
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: Colors.blue.shade200),
            ),
            child: Row(
              children: [
                SizedBox(
                  width: 12,
                  height: 12,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.blue.shade700),
                ),
                const SizedBox(width: 8),
                Text(
                  '自动控制模式运行中...',
                  style: TextStyle(
                    fontSize: 12,
                    color: Colors.blue.shade700,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
          )
        else
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: provider.isCollecting
                      ? () => provider.stopCollection()
                      : () async => await provider.startCollection(),
                  icon: Icon(
                    provider.isCollecting ? Icons.stop : Icons.play_arrow,
                    size: 16,
                  ),
                  label: Text(
                    provider.isCollecting ? '停止' : '开始',
                    style: const TextStyle(fontSize: 12),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: provider.isCollecting ? Colors.red : Colors.green,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 8),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                onPressed: () async {
                  // Perform spectrum collection
                  provider.collectSingleSpectrum();
                },
                icon: const Icon(Icons.camera_alt, size: 16),
                style: IconButton.styleFrom(
                  backgroundColor: Colors.blue.shade100,
                  foregroundColor: Colors.blue.shade700,
                ),
                tooltip: '单次采集',
              ),
            ],
          ),
        const SizedBox(height: 4),
        Text(
          provider.status,
          style: TextStyle(
            fontSize: 10,
            color: Colors.grey.shade600,
          ),
        ),
      ],
    );
  }

  Widget _buildSensorControls(SensorProvider provider) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '传感器采集',
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w500,
          ),
        ),
        const SizedBox(height: 8),
        if (provider.isAutoControlMode)
           Container(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
            decoration: BoxDecoration(
              color: Colors.blue.shade50,
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: Colors.blue.shade200),
            ),
            child: Row(
              children: [
                SizedBox(
                  width: 12,
                  height: 12,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.blue.shade700),
                ),
                const SizedBox(width: 8),
                Text(
                  '自动控制模式运行中...',
                  style: TextStyle(
                    fontSize: 12,
                    color: Colors.blue.shade700,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
          )
        else
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: provider.isCollecting
                      ? () => provider.stopCollection()
                      : () async => await provider.startCollection(),
                  icon: Icon(
                    provider.isCollecting ? Icons.stop : Icons.play_arrow,
                    size: 16,
                  ),
                  label: Text(
                    provider.isCollecting ? '停止' : '开始',
                    style: const TextStyle(fontSize: 12),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: provider.isCollecting ? Colors.red : Colors.green,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 8),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                onPressed: () => provider.collectSingleReading(),
                icon: const Icon(Icons.refresh, size: 16),
                style: IconButton.styleFrom(
                  backgroundColor: Colors.orange.shade100,
                  foregroundColor: Colors.orange.shade700,
                ),
                tooltip: '单次读取',
              ),
            ],
          ),
        const SizedBox(height: 4),
        Text(
          provider.status,
          style: TextStyle(
            fontSize: 10,
            color: Colors.grey.shade600,
          ),
        ),
      ],
    );
  }

  Widget _buildSpectrumSection() {
    return Consumer<SpectrumProvider>(
      builder: (context, provider, child) {
        return Column(
          children: [
            SpectrumChart(
              spectrumData: provider.currentSpectrum,
              height: 350,
            ),
            if (provider.currentSpectrum != null) ...[
              const SizedBox(height: 8),
              _buildSpectrumInfo(provider.currentSpectrum!, provider),
            ],
          ],
        );
      },
    );
  }

  Widget _buildSpectrumInfo(spectrum, SpectrumProvider provider) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.blue.shade50,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: Colors.blue.shade200),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: [
          _buildInfoItem('积分时间', '${provider.integrationTime} μs'),
          _buildInfoItem('平均扫描', '${provider.scansToAverage}'),
          _buildInfoItem('数据点数', '${spectrum.wavelengths.length}'),
          _buildInfoItem('波长范围', '${spectrum.wavelengths.first.toStringAsFixed(1)}-${spectrum.wavelengths.last.toStringAsFixed(1)} nm'),
        ],
      ),
    );
  }

  Widget _buildInfoItem(String label, String value) {
    return Column(
      children: [
        Text(
          value,
          style: const TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.bold,
            color: Colors.black87,
          ),
        ),
        Text(
          label,
          style: TextStyle(
            fontSize: 10,
            color: Colors.grey.shade700,
          ),
        ),
      ],
    );
  }

  Widget _buildSensorSection() {
    return Consumer<SensorProvider>(
      builder: (context, provider, child) {
        return SensorDataWidget(
          sensorData: provider.currentSensorData,
          historicalData: provider.historicalSensorData,
          isCollecting: provider.isCollecting,
          status: provider.status,
        );
      },
    );
  }

  Widget _buildFloatingActionButton() {
    return Consumer2<SpectrumProvider, SensorProvider>(
      builder: (context, spectrumProvider, sensorProvider, child) {
        return FloatingActionButton(
          onPressed: () => _showExitDialog(spectrumProvider, sensorProvider),
          backgroundColor: Colors.red.shade600,
          foregroundColor: Colors.white,
          child: const Icon(Icons.power_settings_new),
        );
      },
    );
  }

  void _handleMenuAction(String value, SpectrumProvider spectrumProvider, SensorProvider sensorProvider) {
    switch (value) {
      case 'settings':
        _showSettingsDialog(spectrumProvider, sensorProvider);
        break;
      case 'about':
        _showAboutDialog();
        break;
    }
  }

  void _showSettingsDialog(SpectrumProvider spectrumProvider, SensorProvider sensorProvider) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('设置'),
        content: const Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('设置面板即将推出...'),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('关闭'),
          ),
        ],
      ),
    );
  }

  void _showAboutDialog() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('关于'),
        content: const Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('HY 数据采集应用'),
            SizedBox(height: 8),
            Text('版本: 1.0.0'),
            SizedBox(height: 8),
            Text('集成在线采集系统'),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('关闭'),
          ),
        ],
      ),
    );
  }

  void _showExitDialog(SpectrumProvider spectrumProvider, SensorProvider sensorProvider) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('退出应用'),
        content: const Text('确定要退出吗？所有数据采集将被停止。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () async {
              // Stop all data collection
              spectrumProvider.stopCollection();
              sensorProvider.stopCollection();
              
              // Close devices
              await spectrumProvider.closeDevice();
              sensorProvider.disconnect();
              
              Navigator.of(context).pop();
              
              // Exit the app
              if (context.mounted) {
                Navigator.of(context).pushReplacementNamed('/exit');
              }
            },
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('退出'),
          ),
        ],
      ),
    );
  }
}
