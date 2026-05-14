import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'providers/spectrum_provider.dart';
import 'providers/sensor_provider.dart';
import 'providers/valve_control_provider.dart';
import 'providers/device_reset_provider.dart';
import 'providers/online_analysis_provider.dart';
import 'screens/app_layout_screen.dart';
import 'config/app_theme.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => SpectrumProvider()),
        ChangeNotifierProvider(create: (_) => SensorProvider()),
        ChangeNotifierProvider(create: (_) => ValveControlProvider()),
        ChangeNotifierProvider(create: (_) => DeviceResetProvider()),
        ChangeNotifierProvider(create: (_) => OnlineAnalysisProvider()),
      ],
      builder: (context, child) {
        // 设置传感器provider和设备重置provider的关联
        final sensorProvider = Provider.of<SensorProvider>(context, listen: false);
        final spectrumProvider = Provider.of<SpectrumProvider>(context, listen: false);
        final resetProvider = Provider.of<DeviceResetProvider>(context, listen: false);
        final onlineAnalysisProvider = Provider.of<OnlineAnalysisProvider>(context, listen: false);
        
        sensorProvider.setDeviceResetProvider(resetProvider);
        spectrumProvider.setDeviceResetProvider(resetProvider);
        
        // 设置在线分析的光谱数据回调
        onlineAnalysisProvider.setSpectrumDataCallback((spectrumData) {
          spectrumProvider.updateCurrentSpectrum(spectrumData);
        });
        
        return MaterialApp(
          title: '优谱德在线数据采集系统',
          theme: AppTheme.theme,
          home: const AppLayoutScreen(),
          routes: {
            '/exit': (context) => const ExitScreen(),
          },
          debugShowCheckedModeBanner: false,
        );
      },
    );
  }
}

class ExitScreen extends StatelessWidget {
  const ExitScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey.shade900,
      body: const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.power_settings_new,
              size: 64,
              color: Colors.white,
            ),
            SizedBox(height: 16),
            Text(
              'Application Closed',
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.bold,
                color: Colors.white,
              ),
            ),
            SizedBox(height: 8),
            Text(
              'All data collection has been stopped',
              style: TextStyle(
                fontSize: 16,
                color: Colors.white70,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
