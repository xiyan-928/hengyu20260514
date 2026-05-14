import 'dart:io';
import 'dart:typed_data';
import '../models/spectrum_data.dart';
import 'api_service.dart';

/// SPC file handler that uses backend API for conversion
class ApiSpcHandler {
  final ApiService _apiService;

  ApiSpcHandler(this._apiService);

  /// Convert SpectrumData to SPC format using backend API and write to file
  static Future<bool> writeSpectrumToSpc(SpectrumData spectrum, String filePath) async {
    try {
      final apiService = ApiService();
      
      // Call backend API to convert spectrum data to SPC format
      print('Converting spectrum to SPC format via backend API...');
      final response = await apiService.convertToSpc(spectrum.toJson());
      
      if (response.success && response.data != null) {
        // The backend returns metadata including file_path
        final serverFilePath = response.data!['file_path'] as String;
        
        // Since we are running locally, try to copy the file
        try {
            final serverFile = File(serverFilePath);
            if (await serverFile.exists()) {
                await serverFile.copy(filePath);
                print('Spectrum data copied from $serverFilePath to: $filePath');
                apiService.dispose();
                return true;
            }
        } catch (e) {
            print('Could not copy file from server path: $e');
        }
        
        print('SPC conversion successful on server: $serverFilePath');
        apiService.dispose();
        return true;
      } else {
        print('SPC conversion failed: ${response.message}');
        apiService.dispose();
        return false;
      }
    } catch (e) {
      print('Error saving SPC file: $e');
      return false;
    }
  }

  /// Read SPC file - this functionality remains local as it's for verification
  static Future<SpectrumData?> readSpcFile(String filePath) async {
    try {
      final file = File(filePath);
      if (!await file.exists()) {
        print('SPC file not found: $filePath');
        return null;
      }

      final bytes = await file.readAsBytes();
      return _parseSpcBytes(bytes);
    } catch (e) {
      print('Error reading SPC file: $e');
      return null;
    }
  }

  /// Basic SPC file parsing for verification (simplified version)
  static SpectrumData? _parseSpcBytes(Uint8List bytes) {
    try {
      final buffer = ByteData.sublistView(bytes);
      
      // Check signature
      final signature = buffer.getUint32(0, Endian.little);
      if (signature != 0x4B435053) { // 'SPCK'
        print('Invalid SPC file signature: 0x${signature.toRadixString(16)}');
        return null;
      }

      // Read header information
      final numPoints = buffer.getUint32(12, Endian.little);
      final scansToAverage = buffer.getUint32(36, Endian.little);
      final timestamp = buffer.getUint32(44, Endian.little);

      // Check flags
      final flags = buffer.getUint8(9);
      final hasXValues = (flags & 0x80) != 0; // TXVALS flag

      if (!hasXValues) {
        print('SPC file does not contain X values');
        return null;
      }

      // Read data starting at offset 544 (512 + 32)
      final wavelengths = <double>[];
      final intensities = <int>[];

      final dataOffset = 512 + 32; // Header + sub-header

      // Read X values (wavelengths)
      for (int i = 0; i < numPoints; i++) {
        final x = buffer.getFloat32(dataOffset + (i * 4), Endian.little);
        wavelengths.add(x);
      }

      // Read Y values (intensities)
      final yOffset = dataOffset + (numPoints * 4);
      for (int i = 0; i < numPoints; i++) {
        final y = buffer.getFloat32(yOffset + (i * 4), Endian.little);
        intensities.add(y.round());
      }

      return SpectrumData(
        wavelengths: wavelengths,
        intensities: intensities,
        timestamp: DateTime.fromMillisecondsSinceEpoch(timestamp * 1000),
        length: wavelengths.length,
        integrationTime: 1000, // Default value
        scansToAverage: scansToAverage,
      );
    } catch (e) {
      print('Error parsing SPC bytes: $e');
      return null;
    }
  }
}
