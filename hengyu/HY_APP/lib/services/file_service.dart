import 'dart:io';
import 'dart:convert';
import 'package:csv/csv.dart';
import 'package:intl/intl.dart';
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import '../models/spectrum_data.dart';
import '../models/sensor_data.dart';
import '../models/absorbance_data.dart';
import 'settings_service.dart';
import 'api_spc_handler.dart';
import 'api_service.dart';

// File format enumeration
enum SpectrumFileFormat {
  csv,
  spc, // SPC format via backend API
}

class FileService {
  // Singleton pattern
  static final FileService _instance = FileService._internal();

  factory FileService() {
    return _instance;
  }

  FileService._internal();

  static const String spectrumFilePrefix = 'SPEC';
  static const String sensorFileName = 'SENSOR.csv';
  static const String absorbanceFileName = 'ABSORBANCE.csv';
  static const String spcFolderName = 'SPC';

  // Cache for data directory
  Directory? _cachedDataDir;
  DateTime? _lastCacheUpdate;
  DateTime? _lastSaveDate;

  // Current session directory path (if collection is active)
  String? _currentSessionPath;

  /// Start a new data collection session
  /// Creates a new directory in format YYYYMMDD-NN
  Future<void> startNewSession() async {
    try {
      final baseDir = await getDataDirectory();
      final dateStr = DateFormat('yyyyMMdd').format(DateTime.now());

      // Find existing directories for today to determine next serial number
      int maxSerial = 0;
      if (await baseDir.exists()) {
        final entities = await baseDir.list().toList();
        for (final entity in entities) {
          if (entity is Directory) {
            final dirName = entity.path.split(Platform.pathSeparator).last;
            if (dirName.startsWith('$dateStr-')) {
              final parts = dirName.split('-');
              if (parts.length >= 2) {
                final serial = int.tryParse(parts[1]);
                if (serial != null && serial > maxSerial) {
                  maxSerial = serial;
                }
              }
            }
          }
        }
      }

      // Create new session directory with incremented serial
      final nextSerial = (maxSerial + 1).toString().padLeft(2, '0');
      final newSessionDirName = '$dateStr-$nextSerial';
      final newSessionDir = Directory(
          '${baseDir.path}${Platform.pathSeparator}$newSessionDirName');

      if (!await newSessionDir.exists()) {
        await newSessionDir.create(recursive: true);
      }

      _currentSessionPath = newSessionDir.path;
      print('Started new session: $_currentSessionPath');
    } catch (e) {
      print('Error starting new session: $e');
      _currentSessionPath = null; // Fallback to default logic
    }
  }

  /// End current session
  void endSession() {
    _currentSessionPath = null;
  }

  /// Get directory for saving data (Session dir if active, otherwise Monthly dir)
  Future<Directory> getSaveDirectory([DateTime? date]) async {
    // Priority 1: Use current session directory if active (ignoring date)
    if (_currentSessionPath != null) {
      final sessionDir = Directory(_currentSessionPath!);
      if (await sessionDir.exists()) {
        return sessionDir;
      }
    }

    // Priority 2: Fallback to monthly directory based on date
    return await getMonthlyDirectory(date);
  }

  Future<Directory> getSpcDirectory(
    Directory saveDir, [
    String? subDirectory,
  ]) async {
    final parts = <String>[saveDir.path, spcFolderName];
    if (subDirectory != null && subDirectory.isNotEmpty) {
      parts.add(subDirectory);
    }
    final dir = Directory(parts.join(Platform.pathSeparator));
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    return dir;
  }

  // Store the path of the latest saved SPC file
  static String? latestSpcPath;

  /// Request storage permissions
  Future<bool> requestStoragePermission() async {
    if (Platform.isAndroid) {
      final status = await Permission.storage.request();
      return status.isGranted;
    }
    return true; // iOS doesn't need explicit storage permission for app documents
  }

  /// Get the base directory for data storage
  Future<Directory> getDataDirectory() async {
    // Check cache first (valid for 1 minute)
    if (_cachedDataDir != null &&
        _lastCacheUpdate != null &&
        DateTime.now().difference(_lastCacheUpdate!).inMinutes < 1) {
      return _cachedDataDir!;
    }

    final settingsService = SettingsService();
    final useCustomDirectory = await settingsService.getUseCustomDirectory();

    if (useCustomDirectory) {
      final customPath = await settingsService.getCustomDirectory();
      if (customPath != null) {
        final customDir = Directory(customPath);
        if (await customDir.exists()) {
          return customDir;
        }
      }
    }

    // Fallback to default directory
    Directory appDir;

    if (Platform.isAndroid) {
      // Use external storage for Android
      appDir = await getExternalStorageDirectory() ??
          await getApplicationDocumentsDirectory();
    } else if (Platform.isWindows) {
      // Use Documents folder for Windows
      final homeDir =
          Platform.environment['USERPROFILE'] ?? Platform.environment['HOME'];
      if (homeDir != null) {
        final documentsDir = Directory('$homeDir\\Documents\\HY_Data');
        if (!await documentsDir.exists()) {
          await documentsDir.create(recursive: true);
        }
        appDir = documentsDir;
      } else {
        appDir = await getApplicationDocumentsDirectory();
      }
    } else {
      // Use application documents directory for other platforms
      appDir = await getApplicationDocumentsDirectory();
    }

    // Update cache
    _cachedDataDir = appDir;
    _lastCacheUpdate = DateTime.now();

    return appDir;
  }

  /// Get or create the monthly directory (YYMM format)
  Future<Directory> getMonthlyDirectory([DateTime? date]) async {
    final baseDir = await getDataDirectory();
    final targetDate = date ?? DateTime.now();
    final monthlyDirName = DateFormat('yyMM').format(targetDate);

    final monthlyDir = Directory('${baseDir.path}/$monthlyDirName');
    if (!await monthlyDir.exists()) {
      await monthlyDir.create(recursive: true);
    }

    return monthlyDir;
  }

  /// Save spectrum data to file (CSV or SPC format via API)
  Future<bool> saveSpectrumData(SpectrumData spectrumData,
      [String? customId,
      SpectrumFileFormat format = SpectrumFileFormat.spc]) async {
    try {
      await requestStoragePermission();

      // Use current system time from frontend instead of spectrum timestamp
      final currentTime = DateTime.now();
      final saveDir =
          await getSaveDirectory(currentTime); // Use Session Dir if active
      final dateStr = DateFormat('yyyy-MM-dd').format(currentTime);
      final timeStr = DateFormat('HHmmss').format(currentTime);
      final id = customId ?? timeStr;

      String fileName;
      String savedPath;
      bool success;

      switch (format) {
        case SpectrumFileFormat.csv:
          fileName = '$dateStr-$spectrumFilePrefix-$id.csv';
          final file = File('${saveDir.path}/$fileName');
          savedPath = file.path;
          // Create updated spectrum data with current system timestamp
          final updatedSpectrumData = SpectrumData(
            timestamp: currentTime, // Use current frontend time
            intensities: spectrumData.intensities,
            length: spectrumData.intensities.length,
            integrationTime: spectrumData.integrationTime,
            scansToAverage: spectrumData.scansToAverage,
          );
          await file.writeAsString(updatedSpectrumData.toCsv());
          success = true;
          // Clear the last SPC reference so sensor rows do not point to an old SPC file.
          latestSpcPath = null;
          break;
        case SpectrumFileFormat.spc:
          fileName = '$dateStr-$spectrumFilePrefix-$id.spc';
          final spcDir = await getSpcDirectory(saveDir);
          final filePath = '${spcDir.path}${Platform.pathSeparator}$fileName';
          savedPath = filePath;
          // Create updated spectrum data with current system timestamp for SPC saving
          final updatedSpectrumData = SpectrumData(
            timestamp: currentTime, // Use current frontend time
            intensities: spectrumData.intensities,
            length: spectrumData.intensities.length,
            integrationTime: spectrumData.integrationTime,
            scansToAverage: spectrumData.scansToAverage,
          );
          success = await ApiSpcHandler.writeSpectrumToSpc(
              updatedSpectrumData, filePath);

          if (success) {
            latestSpcPath = '$spcFolderName/$fileName';
            print('Updated latest SPC path: $latestSpcPath');
            await _copyLatestReferenceSpcFiles(saveDir);
          }
          break;
      }

      if (success) {
        print('Spectrum data saved to: $savedPath');
      }
      return success;
    } catch (e) {
      print('Error saving spectrum data: $e');
      return false;
    }
  }

  /// Save spectrum data to both CSV and SPC formats
  Future<bool> saveSpectrumDataBothFormats(SpectrumData spectrumData,
      [String? customId]) async {
    final csvSuccess =
        await saveSpectrumData(spectrumData, customId, SpectrumFileFormat.csv);
    final spcSuccess =
        await saveSpectrumData(spectrumData, customId, SpectrumFileFormat.spc);
    return csvSuccess && spcSuccess;
  }

  Future<void> _copyLatestReferenceSpcFiles(Directory saveDir) async {
    final apiService = ApiService();
    try {
      final darkDir = await getSpcDirectory(saveDir, 'dark');
      final darkResponse = await apiService.convertLatestDarkToSpc();
      if (darkResponse.success && darkResponse.data != null) {
        final fileName =
            (darkResponse.data!['file_name'] as String?) ?? 'dark.spc';
        await ApiSpcHandler.copyServerSpcFile(
          darkResponse.data!,
          '${darkDir.path}${Platform.pathSeparator}$fileName',
        );
      } else {
        print('No dark SPC copied: ${darkResponse.message}');
      }

      final blankDir = await getSpcDirectory(saveDir, 'blank');
      for (final blankType in const ['blank_before', 'blank_after']) {
        final blankResponse =
            await apiService.convertLatestBlankToSpc(blankType);
        if (blankResponse.success && blankResponse.data != null) {
          final fileName =
              (blankResponse.data!['file_name'] as String?) ?? '$blankType.spc';
          await ApiSpcHandler.copyServerSpcFile(
            blankResponse.data!,
            '${blankDir.path}${Platform.pathSeparator}$fileName',
          );
        } else {
          print('No $blankType SPC copied: ${blankResponse.message}');
        }
      }
    } catch (e) {
      print('Error copying reference SPC files: $e');
    } finally {
      apiService.dispose();
    }
  }

  /// Save sensor data to file using unified CSV format
  /// Columns: Date, Sensor1, Sensor2, Sensor3, Sensor4, ...
  Future<bool> saveSensorDataUnified(List<SensorData> sensorDataList,
      [DateTime? date]) async {
    try {
      await requestStoragePermission();

      final targetDate = date ?? DateTime.now();
      final saveDir =
          await getSaveDirectory(targetDate); // Use Session Dir if active
      final dateStr = DateFormat('yyyy-MM-dd').format(targetDate);
      final fileName = '$dateStr-$sensorFileName';

      final file = File('${saveDir.path}/$fileName');

      // Get all unique sensor types from the data
      final Set<String> sensorTypes =
          sensorDataList.map((data) => data.deviceType).toSet();

      bool fileExists = await file.exists();
      Map<String, Map<String, double>> existingData = {};

      // Read existing data if file exists
      if (fileExists) {
        final existingContent = await file.readAsString();
        final rows =
            existingContent.split('\n').where((row) => row.isNotEmpty).toList();

        if (rows.isNotEmpty) {
          // Parse header to get sensor types
          final headerRow = rows.first.split(',');
          final existingSensorTypes =
              headerRow.skip(1).toList(); // Skip 'Date' column

          // Parse data rows
          for (int i = 1; i < rows.length; i++) {
            final rowData = rows[i].split(',');
            if (rowData.isNotEmpty) {
              final date = rowData[0];
              existingData[date] = {};

              for (int j = 1;
                  j < rowData.length && j - 1 < existingSensorTypes.length;
                  j++) {
                final value = double.tryParse(rowData[j]);
                if (value != null) {
                  existingData[date]![existingSensorTypes[j - 1]] = value;
                }
              }
            }
          }

          // Merge sensor types
          sensorTypes.addAll(existingSensorTypes);
        }
      }

      // Group new data by current date (use system time instead of sensor timestamp)
      final currentDate = DateTime.now();
      final dateKey = DateFormat('yyyy-MM-dd').format(currentDate);
      final Map<String, Map<String, double>> newDataByDate = {};

      if (!newDataByDate.containsKey(dateKey)) {
        newDataByDate[dateKey] = {};
      }

      // Use current system time for all sensor data
      for (final sensorData in sensorDataList) {
        newDataByDate[dateKey]![sensorData.deviceType] = sensorData.value;
      }

      // Merge existing and new data
      for (final entry in newDataByDate.entries) {
        final dateKey = entry.key;
        final sensorValues = entry.value;

        if (existingData.containsKey(dateKey)) {
          existingData[dateKey]!.addAll(sensorValues);
        } else {
          existingData[dateKey] = sensorValues;
        }
      }

      // Write unified CSV
      final allSensorTypes = sensorTypes.toList()..sort();
      final List<List<String>> csvData = [];

      // Header
      csvData.add(['Date', ...allSensorTypes]);

      // Data rows
      final sortedDates = existingData.keys.toList()..sort();
      for (final date in sortedDates) {
        final rowData = [date];
        for (final sensorType in allSensorTypes) {
          final value = existingData[date]![sensorType];
          rowData.add(value?.toStringAsFixed(2) ?? '');
        }
        csvData.add(rowData);
      }

      final csvString = const ListToCsvConverter().convert(csvData);
      await file.writeAsString(csvString);

      print('Unified sensor data saved to: ${file.path}');
      return true;
    } catch (e) {
      print('Error saving unified sensor data: $e');
      return false;
    }
  }

  /// Save sensor data to file (original format for compatibility)
  Future<bool> saveSensorData(List<SensorData> sensorDataList,
      [DateTime? date]) async {
    try {
      await requestStoragePermission();

      final targetDate = date ?? DateTime.now();
      final saveDir =
          await getSaveDirectory(targetDate); // Use Session Dir if active
      final dateStr = DateFormat('yyyy-MM-dd').format(targetDate);
      final fileName = '$dateStr-$sensorFileName';

      final file = File('${saveDir.path}/$fileName');

      // Check if file exists to determine if we need to write header
      final bool fileExists = await file.exists();

      final List<List<String>> csvData = [];

      // Add header if file doesn't exist
      if (!fileExists) {
        csvData.add(SensorData.getCsvHeader().split(','));
      }

      // Add data rows with current system timestamp
      final currentTime =
          DateTime.now(); // Use current system time from frontend
      for (final sensorData in sensorDataList) {
        // Create new sensor data with current system timestamp
        final updatedSensorData = SensorData(
          deviceType: sensorData.deviceType,
          value: sensorData.value,
          unit: sensorData.unit,
          timestamp:
              currentTime, // Use current frontend time instead of backend timestamp
          deviceIp: sensorData.deviceIp,
          devicePort: sensorData.devicePort,
        );
        csvData.add(updatedSensorData.toCsvRow().split(','));
      }

      final csvString = const ListToCsvConverter().convert(csvData);

      // Append to file if it exists, otherwise create new file
      if (fileExists) {
        await file.writeAsString(csvString, mode: FileMode.append);
      } else {
        await file.writeAsString(csvString);
      }

      print('Sensor data saved to: ${file.path}');
      return true;
    } catch (e) {
      print('Error saving sensor data: $e');
      return false;
    }
  }

  /// Append single sensor data to daily CSV file
  Future<bool> appendSensorData(SensorData sensorData, [DateTime? date]) async {
    return await saveSensorData([sensorData], date);
  }

  /// Get list of saved spectrum files for a given date
  Future<List<String>> getSpectrumFiles([DateTime? date]) async {
    try {
      final targetDate = date ?? DateTime.now();
      final monthlyDir = await getMonthlyDirectory(targetDate);
      final dateStr = DateFormat('yyyy-MM-dd').format(targetDate);

      final files = await monthlyDir.list().toList();
      final spectrumFiles = files
          .where((file) =>
              file is File &&
              file.path.contains(dateStr) &&
              file.path.contains(spectrumFilePrefix))
          .map((file) => file.path)
          .toList();

      return spectrumFiles;
    } catch (e) {
      print('Error getting spectrum files: $e');
      return [];
    }
  }

  /// Get sensor data file path for a given date
  Future<String?> getSensorDataFile([DateTime? date]) async {
    try {
      final targetDate = date ?? DateTime.now();
      final monthlyDir = await getMonthlyDirectory(targetDate);
      final dateStr = DateFormat('yyyy-MM-dd').format(targetDate);
      final fileName = '$dateStr-$sensorFileName';

      final file = File('${monthlyDir.path}/$fileName');
      if (await file.exists()) {
        return file.path;
      }
      return null;
    } catch (e) {
      print('Error getting sensor data file: $e');
      return null;
    }
  }

  /// Get available monthly directories
  Future<List<String>> getAvailableMonths() async {
    try {
      final baseDir = await getDataDirectory();
      final directories = await baseDir.list().toList();

      final months = directories
          .where((dir) => dir is Directory)
          .map((dir) => dir.path.split('/').last)
          .where((name) => RegExp(r'^\d{4}$').hasMatch(name)) // YYMM format
          .toList();

      months.sort();
      return months;
    } catch (e) {
      print('Error getting available months: $e');
      return [];
    }
  }

  /// Delete old data files (older than specified days)
  Future<bool> cleanupOldFiles(int daysToKeep) async {
    try {
      final baseDir = await getDataDirectory();
      final cutoffDate = DateTime.now().subtract(Duration(days: daysToKeep));

      final directories = await baseDir.list().toList();

      for (final dir in directories) {
        if (dir is Directory) {
          final dirName = dir.path.split('/').last;
          if (RegExp(r'^\d{4}$').hasMatch(dirName)) {
            // Parse YYMM format
            final year = int.parse('20${dirName.substring(0, 2)}');
            final month = int.parse(dirName.substring(2, 4));
            final dirDate = DateTime(year, month);

            if (dirDate.isBefore(cutoffDate)) {
              await dir.delete(recursive: true);
              print('Deleted old directory: ${dir.path}');
            }
          }
        }
      }

      return true;
    } catch (e) {
      print('Error cleaning up old files: $e');
      return false;
    }
  }

  /// Save a single unified sensor reading row (optimized for size)
  Future<bool> saveSensorDataRow(
    Map<String, SensorData> sensorDataMap, [
    DateTime? date,
    String? spcPath,
    bool? isAlarming,
    int? fanSpeed,
    double? bridgeTemperature,
    double? bridgeLevel,
  ]) async {
    try {
      await requestStoragePermission();

      final targetDate = date ?? DateTime.now();

      // If NOT in a session mode (fallback to monthly), detect day change to refresh directory cache
      if (_currentSessionPath == null) {
        if (_lastSaveDate != null) {
          final lastStr = DateFormat('yyyy-MM-dd').format(_lastSaveDate!);
          final currentStr = DateFormat('yyyy-MM-dd').format(targetDate);
          if (lastStr != currentStr) {
            print(
                '📅 Day changed from $lastStr to $currentStr, clearing directory cache');
            _cachedDataDir = null; // Force refresh
          }
        }
        _lastSaveDate = targetDate;
      }

      final saveDir =
          await getSaveDirectory(targetDate); // Use Session Dir if active
      final dateStr = DateFormat('yyyy-MM-dd').format(targetDate);
      final fileName = '$dateStr-$sensorFileName';

      final file = File('${saveDir.path}/$fileName');

      // Define sensor order for consistent CSV columns
      final orderedSensorTypes = ['PH', 'PH_TEMP', 'TEMP', 'PT100', 'DDL'];
      final activeSensorTypes = orderedSensorTypes
          .where((type) => sensorDataMap.containsKey(type))
          .toList();

      bool fileExists = await file.exists();

      // Create CSV header if file doesn't exist
      if (!fileExists) {
        final header = [
          '时间',
          '日期',
          ...activeSensorTypes.map(_getSensorDisplayName),
          'SPC文件',
          '报警状态',
          '风扇转速',
          '桥接温度(°C)',
          '液位'
        ];
        final headerRow = const ListToCsvConverter().convert([header]);

        // Write with UTF-8 BOM for proper Chinese character display on Windows
        final utf8Bom = [0xEF, 0xBB, 0xBF]; // UTF-8 BOM
        final headerBytes = utf8.encode('$headerRow\n');
        final fileBytes = [...utf8Bom, ...headerBytes];
        await file.writeAsBytes(fileBytes, mode: FileMode.write);
      } else {
        await _ensureSensorCsvExtendedHeader(file);
      }

      // Create data row with current system timestamp and values
      final currentTime =
          DateTime.now(); // Use current system time from frontend
      final timeStr = DateFormat('HH:mm:ss').format(currentTime);
      final dateStr2 = DateFormat('yyyy-MM-dd').format(currentTime);

      final dataRow = [timeStr, dateStr2];
      for (final sensorType in activeSensorTypes) {
        final sensorData = sensorDataMap[sensorType];
        dataRow.add(sensorData?.value.toStringAsFixed(2) ?? '0.00');
      }

      // Add extended fields
      dataRow.add(spcPath ?? '');
      dataRow.add(isAlarming != null ? (isAlarming ? '报警' : '正常') : '');
      dataRow.add(fanSpeed?.toString() ?? '');
      dataRow.add(bridgeTemperature?.toStringAsFixed(2) ?? '');
      dataRow.add(bridgeLevel?.toStringAsFixed(2) ?? '');

      final csvRow = const ListToCsvConverter().convert([dataRow]);

      // Write data in UTF-8 encoding
      final dataBytes = utf8.encode('$csvRow\n');
      await file.writeAsBytes(dataBytes, mode: FileMode.append);

      print(
          '保存传感器数据行: $timeStr -> ${activeSensorTypes.length} 个传感器, SPC: ${spcPath ?? "无"}');
      return true;
    } catch (e) {
      print('保存传感器数据行时出错: $e');
      // Clear cache on error to ensure fresh directory lookup next time
      _cachedDataDir = null;
      return false;
    }
  }

  Future<void> _ensureSensorCsvExtendedHeader(File file) async {
    const requiredColumns = ['桥接温度(°C)', '液位'];
    final content = await file.readAsString(encoding: utf8);
    if (content.isEmpty) {
      return;
    }

    final firstNewline = content.indexOf('\n');
    final headerLine =
        firstNewline >= 0 ? content.substring(0, firstNewline) : content;
    final rest = firstNewline >= 0 ? content.substring(firstNewline) : '';

    final headerCells = const CsvToListConverter(eol: '\n')
        .convert(headerLine.replaceFirst('\ufeff', ''))
        .first
        .map((cell) => cell.toString())
        .toList();
    var changed = false;
    for (final column in requiredColumns) {
      if (!headerCells.contains(column)) {
        headerCells.add(column);
        changed = true;
      }
    }
    if (!changed) {
      return;
    }

    final headerRow = const ListToCsvConverter().convert([headerCells]);
    final updated = '\ufeff$headerRow$rest';
    await file.writeAsString(updated, encoding: utf8, mode: FileMode.write);
  }

  String _getSensorDisplayName(String deviceType) {
    switch (deviceType.toUpperCase()) {
      case 'PH':
        return 'pH值';
      case 'PH_TEMP':
        return 'pH温度(°C)';
      case 'TEMP':
        return '温度(°C)';
      case 'PT100':
        return 'PT100(°C)';
      case 'DDL':
        return '电导率(μS/cm)';
      default:
        return deviceType.toUpperCase();
    }
  }

  /// Save absorbance data to file
  Future<bool> saveAbsorbanceData(AbsorbanceData absorbanceData,
      [DateTime? date]) async {
    try {
      await requestStoragePermission();

      final targetDate = date ?? absorbanceData.timestamp;
      final saveDir =
          await getSaveDirectory(targetDate); // Use Session Dir if active
      final dateStr = DateFormat('yyyy-MM-dd').format(targetDate);
      final fileName = '$dateStr-$absorbanceFileName';
      final file = File('${saveDir.path}/$fileName');

      // Check if file exists and needs header
      final fileExists = await file.exists();

      if (!fileExists) {
        // Create new file with header
        final header = AbsorbanceData.csvHeader();
        await file.writeAsString('$header\n', encoding: utf8);
      }

      // Append data row
      final dataRow = absorbanceData.toCsvRow();
      await file.writeAsString('$dataRow\n',
          mode: FileMode.append, encoding: utf8);

      print('🔥 Absorbance data saved to: ${file.path}');
      return true;
    } catch (e) {
      print('🔥 Error saving absorbance data: $e');
      return false;
    }
  }
}
