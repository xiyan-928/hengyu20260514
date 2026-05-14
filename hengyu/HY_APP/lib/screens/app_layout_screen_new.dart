import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/spectrum_provider.dart';
import '../providers/sensor_provider.dart';
import '../providers/valve_control_provider.dart';
import '../widgets/spectrum_chart.dart';
import '../widgets/sensor_data_widget.dart';
import 'settings_screen.dart';
import 'hardware_control_screen.dart';

class AppLayoutScreen extends StatefulWidget {
  const AppLayoutScreen({super.key});

  @override
  State<AppLayoutScreen> createState() => _AppLayoutScreenState();
}

class _AppLayoutScreenState extends State<AppLayoutScreen> {
  int _selectedIndex = 0;
  bool _isInitialized = false;

  final List<NavigationItem> _navigationItems = [
    NavigationItem(
      icon: Icons.timeline,
      label: '在线采集',
      title: '优谱德在线数据采集系统',
    ),
    NavigationItem(
      icon: Icons.settings,
      label: '设置',
      title: '设置',
    ),
    NavigationItem(
      icon: Icons.hardware,
      label: '硬件控制',
      title: '硬件控制',
    ),
  ];

  @override
  void initState() {
    super.initState();
    _initializeApp();
  }

  Future<void> _initializeApp() async {
    final spectrumProvider = Provider.of<SpectrumProvider>(context, listen: false);
    final sensorProvider = Provider.of<SensorProvider>(context, listen: false);
    final valveProvider = Provider.of<ValveControlProvider>(context, listen: false);

    // Load user settings first
    await spectrumProvider.initialize();

    // Initialize CDS350
    await spectrumProvider.initializeDevice();

    // Initialize sensors with default settings
    await sensorProvider.initializeSensors('192.168.1.12', 502);

    // Initialize valve control
    await valveProvider.initialize();

    setState(() {
      _isInitialized = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        children: [
          _buildSideNavigation(),
          Expanded(
            child: _isInitialized ? _buildMainContent() : _buildLoadingScreen(),
          ),
        ],
      ),
    );
  }

  Widget _buildSideNavigation() {
    return Container(
      width: 200,
      decoration: BoxDecoration(
        color: Colors.blue.shade700,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.1),
            blurRadius: 4,
            offset: const Offset(2, 0),
          ),
        ],
      ),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            child: const Column(
              children: [
                Icon(
                  Icons.analytics,
                  color: Colors.white,
                  size: 40,
                ),
                SizedBox(height: 8),
                Text(
                  'HY 采集系统',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: _navigationItems.length,
              itemBuilder: (context, index) {
                final item = _navigationItems[index];
                final isSelected = index == _selectedIndex;
                return Container(
                  margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  child: Material(
                    color: isSelected ? Colors.white.withOpacity(0.2) : Colors.transparent,
                    borderRadius: BorderRadius.circular(8),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(8),
                      onTap: () {
                        setState(() {
                          _selectedIndex = index;
                        });
                      },
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                        child: Row(
                          children: [
                            Icon(
                              item.icon,
                              color: Colors.white,
                              size: 20,
                            ),
                            const SizedBox(width: 12),
                            Text(
                              item.label,
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 14,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
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
    switch (_selectedIndex) {
      case 0:
        return const DataCollectionContent();
      case 1:
        return const SettingsScreen();
      case 2:
        return const HardwareControlScreen();
      default:
        return const DataCollectionContent();
    }
  }
}

class NavigationItem {
  final IconData icon;
  final String label;
  final String title;

  NavigationItem({
    required this.icon,
    required this.label,
    required this.title,
  });
}

class DataCollectionContent extends StatelessWidget {
  const DataCollectionContent({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey.shade50,
      appBar: AppBar(
        title: const Text(
          '在线数据采集',
          style: TextStyle(
            fontWeight: FontWeight.w600,
            color: Colors.white,
          ),
        ),
        backgroundColor: Colors.blue.shade700,
        elevation: 0,
        automaticallyImplyLeading: false,
      ),
      body: SingleChildScrollView(
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
                    child: _buildSpectrumControls(context, spectrumProvider),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: _buildSensorControls(context, sensorProvider),
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

  Widget _buildSpectrumControls(BuildContext context, SpectrumProvider provider) {
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
          ],
        ),
      ],
    );
  }



  Widget _buildSensorControls(BuildContext context, SensorProvider provider) {
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
        Row(
          children: [
            Expanded(
              child: ElevatedButton.icon(
                onPressed: provider.isCollecting
                    ? () => provider.stopCollection()
                    : () => provider.startCollection(),
                icon: Icon(
                  provider.isCollecting ? Icons.stop : Icons.play_arrow,
                  size: 16,
                ),
                label: Text(
                  provider.isCollecting ? '停止' : '开始',
                  style: const TextStyle(fontSize: 12),
                ),
                style: ElevatedButton.styleFrom(
                  backgroundColor: provider.isCollecting ? Colors.red : Colors.purple,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 8),
                ),
              ),
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
        return Container(
          height: 400,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.grey.shade300),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.show_chart, color: Colors.blue),
                  const SizedBox(width: 8),
                  const Text(
                    '光谱数据',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              Expanded(
                child: provider.currentSpectrum != null
                    ? SpectrumChart(spectrumData: provider.currentSpectrum!)
                    : const Center(
                        child: Text(
                          '暂无光谱数据',
                          style: TextStyle(fontSize: 16, color: Colors.grey),
                        ),
                      ),
              ),
            ],
          ),
        );
      },
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
}
