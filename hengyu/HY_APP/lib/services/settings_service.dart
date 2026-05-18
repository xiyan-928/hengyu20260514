import 'package:shared_preferences/shared_preferences.dart';
import 'dart:io';
import 'file_service.dart';

class SettingsService {
  static const String _integrationTimeKey = 'integration_time';
  static const String _scansToAverageKey = 'scans_to_average';
  static const String _customDirectoryKey = 'custom_directory';
  static const String _useCustomDirectoryKey = 'use_custom_directory';
  static const String _spectrumFileFormatKey = 'spectrum_file_format';
  static const String _spectrumQueryIntervalKey = 'spectrum_query_interval';
  
  // Default values
  static const int defaultIntegrationTime = 10000; // microseconds
  static const int defaultScansToAverage = 3;
  static const int defaultSpectrumQueryInterval = 60; // seconds; 与 HY_Online / upload_client SPC 间隔一致
  static const SpectrumFileFormat defaultSpectrumFileFormat = SpectrumFileFormat.spc;

  /// Get integration time from preferences
  Future<int> getIntegrationTime() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(_integrationTimeKey) ?? defaultIntegrationTime;
  }

  /// Save integration time to preferences
  Future<void> setIntegrationTime(int value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_integrationTimeKey, value);
  }

  /// Get scans to average from preferences
  Future<int> getScansToAverage() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(_scansToAverageKey) ?? defaultScansToAverage;
  }

  /// Save scans to average to preferences
  Future<void> setScansToAverage(int value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_scansToAverageKey, value);
  }

  /// Get spectrum query interval from preferences (in seconds)
  Future<int> getSpectrumQueryInterval() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(_spectrumQueryIntervalKey) ?? defaultSpectrumQueryInterval;
  }

  /// Save spectrum query interval to preferences (in seconds)
  Future<void> setSpectrumQueryInterval(int value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_spectrumQueryIntervalKey, value);
  }

  /// Get custom directory path
  Future<String?> getCustomDirectory() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_customDirectoryKey);
  }

  /// Save custom directory path
  Future<void> setCustomDirectory(String path) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_customDirectoryKey, path);
  }

  /// Get whether to use custom directory
  Future<bool> getUseCustomDirectory() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_useCustomDirectoryKey) ?? false;
  }

  /// Set whether to use custom directory
  Future<void> setUseCustomDirectory(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_useCustomDirectoryKey, value);
  }

  /// Clear custom directory settings
  Future<void> clearCustomDirectory() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_customDirectoryKey);
    await prefs.setBool(_useCustomDirectoryKey, false);
  }

  /// Validate if custom directory exists and is writable
  Future<bool> validateCustomDirectory(String path) async {
    try {
      final directory = Directory(path);
      if (!await directory.exists()) {
        return false;
      }
      
      // Test if we can write to the directory
      final testFile = File('${directory.path}/.test_write');
      await testFile.writeAsString('test');
      await testFile.delete();
      
      return true;
    } catch (e) {
      return false;
    }
  }

  /// Get spectrum file format preference
  Future<SpectrumFileFormat> getSpectrumFileFormat() async {
    final prefs = await SharedPreferences.getInstance();
    final formatString = prefs.getString(_spectrumFileFormatKey) ?? 'spc';
    return formatString == 'csv' ? SpectrumFileFormat.csv : SpectrumFileFormat.spc;
  }

  /// Save spectrum file format preference
  Future<void> setSpectrumFileFormat(SpectrumFileFormat format) async {
    final prefs = await SharedPreferences.getInstance();
    final formatString = format == SpectrumFileFormat.csv ? 'csv' : 'spc';
    await prefs.setString(_spectrumFileFormatKey, formatString);
  }

  /// Get all settings as a map
  Future<Map<String, dynamic>> getAllSettings() async {
    return {
      'integrationTime': await getIntegrationTime(),
      'scansToAverage': await getScansToAverage(),
      'spectrumQueryInterval': await getSpectrumQueryInterval(),
      'customDirectory': await getCustomDirectory(),
      'useCustomDirectory': await getUseCustomDirectory(),
      'spectrumFileFormat': await getSpectrumFileFormat(),
    };
  }
}
