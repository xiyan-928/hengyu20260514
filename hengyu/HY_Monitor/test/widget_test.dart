import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hy_monitor/providers/settings_provider.dart';
import 'package:hy_monitor/main.dart';

void main() {
  testWidgets('HyMonitorApp smoke test', (tester) async {
    final settings = SettingsProvider();
    await tester.pumpWidget(HyMonitorApp(settings: settings));
    expect(find.byType(MaterialApp), findsOneWidget);
  });
}
