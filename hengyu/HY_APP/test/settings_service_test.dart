import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../lib/services/settings_service.dart';

void main() {
  group('SettingsService - Spectrum Query Interval', () {
    late SettingsService settingsService;

    setUp(() {
      settingsService = SettingsService();
    });

    test('should save and retrieve spectrum query interval', () async {
      // Mock SharedPreferences
      SharedPreferences.setMockInitialValues({});

      // Test default value
      int defaultInterval = await settingsService.getSpectrumQueryInterval();
      expect(defaultInterval, equals(5)); // Default is 5 seconds

      // Test setting and getting custom value
      await settingsService.setSpectrumQueryInterval(10);
      int customInterval = await settingsService.getSpectrumQueryInterval();
      expect(customInterval, equals(10));

      // Test getAllSettings includes query interval
      Map<String, dynamic> allSettings = await settingsService.getAllSettings();
      expect(allSettings.containsKey('spectrumQueryInterval'), isTrue);
      expect(allSettings['spectrumQueryInterval'], equals(10));
    });
  });
}
