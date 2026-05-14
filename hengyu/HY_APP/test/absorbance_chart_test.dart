import 'package:flutter_test/flutter_test.dart';
import 'package:hy_app/models/absorbance_data.dart';
import 'package:hy_app/widgets/absorbance_chart.dart';
import 'package:flutter/material.dart';

void main() {
  group('AbsorbanceChart Tests', () {
    testWidgets('AbsorbanceChart displays empty state correctly', (WidgetTester tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AbsorbanceChart(
              absorbanceData: [],
              height: 120,
            ),
          ),
        ),
      );

      expect(find.text('暂无吸光度历史数据'), findsOneWidget);
    });

    testWidgets('AbsorbanceChart displays data correctly', (WidgetTester tester) async {
      final testData = [
        AbsorbanceData(
          value: 5.0,
          timestamp: DateTime.now().subtract(Duration(minutes: 10)),
          lastAcquisitionTime: 1753787609.7088485,
        ),
        AbsorbanceData(
          value: 3.5,
          timestamp: DateTime.now().subtract(Duration(minutes: 5)),
          lastAcquisitionTime: 1753787609.7188485,
        ),
        AbsorbanceData(
          value: 4.2,
          timestamp: DateTime.now(),
          lastAcquisitionTime: 1753787609.7288485,
        ),
      ];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AbsorbanceChart(
              absorbanceData: testData,
              height: 120,
            ),
          ),
        ),
      );

      // Should not show empty state
      expect(find.text('暂无吸光度历史数据'), findsNothing);
      
      // Should show chart container
      expect(find.byType(Container), findsWidgets);
    });

    test('AbsorbanceData equality test', () {
      final data1 = AbsorbanceData(
        value: 5.0,
        timestamp: DateTime.now(),
        lastAcquisitionTime: 1753787609.7088485,
      );

      final data2 = AbsorbanceData(
        value: 3.0, // Different value
        timestamp: DateTime.now().add(Duration(minutes: 1)), // Different timestamp
        lastAcquisitionTime: 1753787609.7088485, // Same acquisition time
      );

      // Should be equal because lastAcquisitionTime is the same
      expect(data1, equals(data2));
    });

    test('AbsorbanceData CSV format test', () {
      final data = AbsorbanceData(
        value: 5.67,
        timestamp: DateTime(2025, 7, 29, 19, 13, 42),
        lastAcquisitionTime: 1753787609.7088485,
      );

      final csv = data.toCsvRow();
      expect(csv, contains('5.67'));
      expect(csv, contains('2025-07-29T19:13:42.000'));
      expect(csv, contains('1753787609.7088485'));
    });
  });
}
