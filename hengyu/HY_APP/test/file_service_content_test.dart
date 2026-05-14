import 'package:flutter_test/flutter_test.dart';
import 'package:hy_app/services/file_service.dart';
import 'package:hy_app/models/dye_content_data.dart';
import 'package:hy_app/models/additive_content_data.dart';
import 'dart:io';

void main() {
  // Ensure Flutter bindings are initialized
  TestWidgetsFlutterBinding.ensureInitialized();
  
  group('FileService - Content Data', () {
    late FileService fileService;
    
    setUp(() {
      fileService = FileService();
    });

    group('Dye Content Data', () {
      test('should save dye content data to file', () async {
        final timestamp = DateTime.now();
        final dyeContentData = DyeContentData(
          value: 85.5,
          timestamp: timestamp,
          lastAcquisitionTime: 123456.789,
        );

        final result = await fileService.saveDyeContentData(dyeContentData);
        expect(result, isTrue);
      });

      test('should create CSV file with correct header for dye content', () async {
        final timestamp = DateTime.now();
        final dyeContentData = DyeContentData(
          value: 92.3,
          timestamp: timestamp,
          lastAcquisitionTime: 987654.321,
        );

        await fileService.saveDyeContentData(dyeContentData);
        
        final filePath = await fileService.getDyeContentDataFile();
        expect(filePath, isNotNull);
        
        if (filePath != null) {
          final file = File(filePath);
          expect(await file.exists(), isTrue);
          
          final content = await file.readAsString();
          expect(content, contains('Timestamp,AcquisitionTime,DyeContent'));
        }
      });

      test('should append data to existing dye content file', () async {
        final timestamp1 = DateTime.now();
        final timestamp2 = timestamp1.add(Duration(minutes: 5));
        
        final dyeContentData1 = DyeContentData(
          value: 75.0,
          timestamp: timestamp1,
          lastAcquisitionTime: 111111.0,
        );
        
        final dyeContentData2 = DyeContentData(
          value: 80.0,
          timestamp: timestamp2,
          lastAcquisitionTime: 222222.0,
        );

        await fileService.saveDyeContentData(dyeContentData1);
        await fileService.saveDyeContentData(dyeContentData2);
        
        final filePath = await fileService.getDyeContentDataFile();
        if (filePath != null) {
          final file = File(filePath);
          final content = await file.readAsString();
          final lines = content.split('\n').where((line) => line.isNotEmpty).toList();
          
          expect(lines.length, greaterThanOrEqualTo(3)); // Header + 2 data rows
          expect(lines[0], contains('Timestamp,AcquisitionTime,DyeContent'));
          expect(lines[1], contains('75.0'));
          expect(lines[2], contains('80.0'));
        }
      });

      test('should get dye content data file path', () async {
        final timestamp = DateTime.now();
        final dyeContentData = DyeContentData(
          value: 88.8,
          timestamp: timestamp,
          lastAcquisitionTime: 444555.666,
        );

        await fileService.saveDyeContentData(dyeContentData);
        
        final filePath = await fileService.getDyeContentDataFile();
        expect(filePath, isNotNull);
        expect(filePath, contains('DYE_CONTENT.csv'));
      });

      test('should return null for non-existent dye content file', () async {
        // Use a future date to ensure file doesn't exist
        final futureDate = DateTime.now().add(Duration(days: 365));
        final filePath = await fileService.getDyeContentDataFile(futureDate);
        expect(filePath, isNull);
      });
    });

    group('Additive Content Data', () {
      test('should save additive content data to file', () async {
        final timestamp = DateTime.now();
        final additiveContentData = AdditiveContentData(
          value: 62.7,
          timestamp: timestamp,
          lastAcquisitionTime: 789123.456,
        );

        final result = await fileService.saveAdditiveContentData(additiveContentData);
        expect(result, isTrue);
      });

      test('should create CSV file with correct header for additive content', () async {
        final timestamp = DateTime.now();
        final additiveContentData = AdditiveContentData(
          value: 55.1,
          timestamp: timestamp,
          lastAcquisitionTime: 147258.369,
        );

        await fileService.saveAdditiveContentData(additiveContentData);
        
        final filePath = await fileService.getAdditiveContentDataFile();
        expect(filePath, isNotNull);
        
        if (filePath != null) {
          final file = File(filePath);
          expect(await file.exists(), isTrue);
          
          final content = await file.readAsString();
          expect(content, contains('Timestamp,AcquisitionTime,AdditiveContent'));
        }
      });

      test('should append data to existing additive content file', () async {
        final timestamp1 = DateTime.now();
        final timestamp2 = timestamp1.add(Duration(minutes: 10));
        
        final additiveContentData1 = AdditiveContentData(
          value: 45.5,
          timestamp: timestamp1,
          lastAcquisitionTime: 333333.0,
        );
        
        final additiveContentData2 = AdditiveContentData(
          value: 50.0,
          timestamp: timestamp2,
          lastAcquisitionTime: 444444.0,
        );

        await fileService.saveAdditiveContentData(additiveContentData1);
        await fileService.saveAdditiveContentData(additiveContentData2);
        
        final filePath = await fileService.getAdditiveContentDataFile();
        if (filePath != null) {
          final file = File(filePath);
          final content = await file.readAsString();
          final lines = content.split('\n').where((line) => line.isNotEmpty).toList();
          
          expect(lines.length, greaterThanOrEqualTo(3)); // Header + 2 data rows
          expect(lines[0], contains('Timestamp,AcquisitionTime,AdditiveContent'));
          expect(lines[1], contains('45.5'));
          expect(lines[2], contains('50.0'));
        }
      });

      test('should get additive content data file path', () async {
        final timestamp = DateTime.now();
        final additiveContentData = AdditiveContentData(
          value: 71.3,
          timestamp: timestamp,
          lastAcquisitionTime: 666777.888,
        );

        await fileService.saveAdditiveContentData(additiveContentData);
        
        final filePath = await fileService.getAdditiveContentDataFile();
        expect(filePath, isNotNull);
        expect(filePath, contains('ADDITIVE_CONTENT.csv'));
      });

      test('should return null for non-existent additive content file', () async {
        // Use a future date to ensure file doesn't exist
        final futureDate = DateTime.now().add(Duration(days: 365));
        final filePath = await fileService.getAdditiveContentDataFile(futureDate);
        expect(filePath, isNull);
      });
    });

    group('Error Handling', () {
      test('should handle file system errors gracefully for dye content', () async {
        // Create data with invalid characters in timestamp that might cause issues
        final invalidTimestamp = DateTime.fromMillisecondsSinceEpoch(0); // Epoch time
        final dyeContentData = DyeContentData(
          value: 99.9,
          timestamp: invalidTimestamp,
          lastAcquisitionTime: 999999.999,
        );

        // Should still return true even if there are minor issues
        final result = await fileService.saveDyeContentData(dyeContentData);
        expect(result, isA<bool>());
      });

      test('should handle file system errors gracefully for additive content', () async {
        // Create data with edge case values
        final additiveContentData = AdditiveContentData(
          value: double.infinity, // Edge case value
          timestamp: DateTime.now(),
          lastAcquisitionTime: double.nan, // Another edge case
        );

        // Should handle gracefully
        final result = await fileService.saveAdditiveContentData(additiveContentData);
        expect(result, isA<bool>());
      });
    });

    group('UTF-8 Encoding', () {
      test('should save files with UTF-8 BOM for proper encoding', () async {
        final timestamp = DateTime.now();
        final dyeContentData = DyeContentData(
          value: 77.7,
          timestamp: timestamp,
          lastAcquisitionTime: 777777.777,
        );

        await fileService.saveDyeContentData(dyeContentData);
        
        final filePath = await fileService.getDyeContentDataFile();
        if (filePath != null) {
          final file = File(filePath);
          final bytes = await file.readAsBytes();
          
          // Check for UTF-8 BOM at the beginning of the file
          expect(bytes.length, greaterThan(3));
          expect(bytes[0], 0xEF); // UTF-8 BOM first byte
          expect(bytes[1], 0xBB); // UTF-8 BOM second byte
          expect(bytes[2], 0xBF); // UTF-8 BOM third byte
        }
      });
    });
  });
}
