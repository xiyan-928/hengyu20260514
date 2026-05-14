import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'providers/devices_provider.dart';
import 'providers/settings_provider.dart';
import 'screens/home_screen.dart';
import 'services/api_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final settings = SettingsProvider();
  await settings.load();

  runApp(HyMonitorApp(settings: settings));
}

class HyMonitorApp extends StatelessWidget {
  const HyMonitorApp({super.key, required this.settings});

  final SettingsProvider settings;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<SettingsProvider>.value(value: settings),
        // DevicesProvider 依赖 settings.baseUrl；base_url 改动后 rebuild
        ChangeNotifierProxyProvider<SettingsProvider, DevicesProvider>(
          create: (_) {
            final api = ApiService(settings.baseUrl);
            return DevicesProvider(api)
              ..start(
                interval: Duration(seconds: settings.devicesRefreshSec),
              );
          },
          update: (_, s, prev) {
            if (prev == null) {
              final api = ApiService(s.baseUrl);
              return DevicesProvider(api)
                ..start(interval: Duration(seconds: s.devicesRefreshSec));
            }
            prev.updateBaseUrl(s.baseUrl);
            prev.updateInterval(Duration(seconds: s.devicesRefreshSec));
            return prev;
          },
        ),
      ],
      child: MaterialApp(
        title: 'HY Monitor',
        debugShowCheckedModeBanner: false,
        theme: _theme(Brightness.light),
        darkTheme: _theme(Brightness.dark),
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: const [
          Locale('zh', 'CN'),
          Locale('en', 'US'),
        ],
        locale: const Locale('zh', 'CN'),
        home: const HomeScreen(),
      ),
    );
  }

  ThemeData _theme(Brightness b) {
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF1565C0),
      brightness: b,
    );
    return ThemeData(
      colorScheme: scheme,
      useMaterial3: true,
      scaffoldBackgroundColor: scheme.surfaceContainerLowest,
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surfaceContainerLowest,
        foregroundColor: scheme.onSurface,
        elevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: scheme.surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
        ),
      ),
      chipTheme: ChipThemeData(
        side: BorderSide(color: scheme.outlineVariant),
      ),
    );
  }
}
