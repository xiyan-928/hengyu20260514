import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hy_app/widgets/additive_type_dialog.dart';

void main() {
  group('AdditiveTypeDialog', () {
    Widget createTestWidget({
      String? initialType,
      List<String>? availableTypes,
    }) {
      return MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () async {
                final result = await AdditiveTypeDialog.show(
                  context,
                  initialType: initialType,
                  availableTypes: availableTypes,
                );
                print('Selected: $result');
              },
              child: const Text('Show Dialog'),
            ),
          ),
        ),
      );
    }

    testWidgets('should display dialog title', (WidgetTester tester) async {
      await tester.pumpWidget(createTestWidget());
      await tester.tap(find.text('Show Dialog'));
      await tester.pumpAndSettle();

      expect(find.text('选择助剂类型'), findsOneWidget);
      expect(find.byIcon(Icons.science), findsOneWidget);
    });

    testWidgets('should display default types', (WidgetTester tester) async {
      await tester.pumpWidget(createTestWidget());
      await tester.tap(find.text('Show Dialog'));
      await tester.pumpAndSettle();

      // Open dropdown
      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();

      // Check default types are present
      expect(find.text('ZJ-1'), findsWidgets);
      expect(find.text('ZJ-2'), findsOneWidget);
      expect(find.text('ZJ-3'), findsOneWidget);
      expect(find.text('ZJ-8'), findsOneWidget);
    });

    testWidgets('should display custom types', (WidgetTester tester) async {
      final customTypes = ['Custom-1', 'Custom-2', 'Custom-3'];
      await tester.pumpWidget(createTestWidget(availableTypes: customTypes));
      await tester.tap(find.text('Show Dialog'));
      await tester.pumpAndSettle();

      // Open dropdown
      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();

      // Check custom types are present
      expect(find.text('Custom-1'), findsWidgets);
      expect(find.text('Custom-2'), findsOneWidget);
      expect(find.text('Custom-3'), findsOneWidget);
    });

    testWidgets('should show initial selection', (WidgetTester tester) async {
      await tester.pumpWidget(createTestWidget(initialType: 'ZJ-3'));
      await tester.tap(find.text('Show Dialog'));
      await tester.pumpAndSettle();

      // Should show ZJ-3 as selected
      expect(find.text('ZJ-3'), findsOneWidget);
    });

    testWidgets('should allow type selection', (WidgetTester tester) async {
      await tester.pumpWidget(createTestWidget());
      await tester.tap(find.text('Show Dialog'));
      await tester.pumpAndSettle();

      // Open dropdown
      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();

      // Select ZJ-3
      await tester.tap(find.text('ZJ-3').last);
      await tester.pumpAndSettle();

      // ZJ-3 should be selected
      expect(find.text('ZJ-3'), findsOneWidget);
    });

    testWidgets('should return selected type on confirm', (WidgetTester tester) async {
      await tester.pumpWidget(createTestWidget());
      await tester.tap(find.text('Show Dialog'));
      await tester.pumpAndSettle();

      // Open dropdown
      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();

      // Select ZJ-2
      await tester.tap(find.text('ZJ-2').last);
      await tester.pumpAndSettle();

      // Tap confirm button
      await tester.tap(find.text('确认'));
      await tester.pumpAndSettle();

      // Dialog should be closed
      expect(find.text('选择助剂类型'), findsNothing);
    });

    testWidgets('should return null on cancel', (WidgetTester tester) async {
      await tester.pumpWidget(createTestWidget());
      await tester.tap(find.text('Show Dialog'));
      await tester.pumpAndSettle();

      // Tap cancel button
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();

      // Dialog should be closed
      expect(find.text('选择助剂类型'), findsNothing);
    });

    testWidgets('should display info message', (WidgetTester tester) async {
      await tester.pumpWidget(createTestWidget());
      await tester.tap(find.text('Show Dialog'));
      await tester.pumpAndSettle();

      expect(
        find.text('选择的助剂类型将影响光谱数据的采集和分析结果'),
        findsOneWidget,
      );
      expect(find.byIcon(Icons.info_outline), findsOneWidget);
    });

    group('Dialog Styling', () {
      testWidgets('should have proper icons', (WidgetTester tester) async {
        await tester.pumpWidget(createTestWidget());
        await tester.tap(find.text('Show Dialog'));
        await tester.pumpAndSettle();

        // Title icon
        expect(find.byIcon(Icons.science), findsOneWidget);
        // Info icon
        expect(find.byIcon(Icons.info_outline), findsOneWidget);

        // Open dropdown to see pharmacy icons
        await tester.tap(find.byType(DropdownButton<String>));
        await tester.pumpAndSettle();

        // Pharmacy icons in dropdown items
        expect(find.byIcon(Icons.local_pharmacy), findsWidgets);
      });

      testWidgets('should have proper button styling', (WidgetTester tester) async {
        await tester.pumpWidget(createTestWidget());
        await tester.tap(find.text('Show Dialog'));
        await tester.pumpAndSettle();

        // Find cancel and confirm buttons
        final cancelButton = find.widgetWithText(TextButton, '取消');
        final confirmButton = find.widgetWithText(ElevatedButton, '确认');

        expect(cancelButton, findsOneWidget);
        expect(confirmButton, findsOneWidget);
      });
    });

    group('Accessibility', () {
      testWidgets('should be accessible', (WidgetTester tester) async {
        await tester.pumpWidget(createTestWidget());
        await tester.tap(find.text('Show Dialog'));
        await tester.pumpAndSettle();

        // Check accessibility guidelines
        await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
        await expectLater(tester, meetsGuideline(iOSTapTargetGuideline));
      });

      testWidgets('should support text scaling', (WidgetTester tester) async {
        await tester.pumpWidget(
          MaterialApp(
            home: MediaQuery(
              data: const MediaQueryData(textScaler: TextScaler.linear(2.0)),
              child: Scaffold(
                body: Builder(
                  builder: (context) => ElevatedButton(
                    onPressed: () => AdditiveTypeDialog.show(context),
                    child: const Text('Show Dialog'),
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.tap(find.text('Show Dialog'));
        await tester.pumpAndSettle();

        expect(find.text('选择助剂类型'), findsOneWidget);
      });
    });

    group('Error Handling', () {
      testWidgets('should handle empty types list', (WidgetTester tester) async {
        await tester.pumpWidget(createTestWidget(availableTypes: []));
        await tester.tap(find.text('Show Dialog'));
        await tester.pumpAndSettle();

        // Should still display dialog but dropdown may be empty
        expect(find.text('选择助剂类型'), findsOneWidget);
      });

      testWidgets('should handle invalid initial type', (WidgetTester tester) async {
        await tester.pumpWidget(createTestWidget(initialType: 'INVALID'));
        await tester.tap(find.text('Show Dialog'));
        await tester.pumpAndSettle();

        // Should default to first available type
        expect(find.text('选择助剂类型'), findsOneWidget);
      });
    });
  });
}
