import 'package:intl/intl.dart';
import 'package:flutter/material.dart';

class DateTimeUtils {
  /// Format timestamp for display
  static String formatTimestamp(DateTime dateTime) {
    return DateFormat('yyyy-MM-dd HH:mm:ss').format(dateTime);
  }

  /// Format date for file naming (YYYY-MM-DD)
  static String formatDateForFile(DateTime dateTime) {
    return DateFormat('yyyy-MM-dd').format(dateTime);
  }

  /// Format month for directory naming (YYMM)
  static String formatMonthForDirectory(DateTime dateTime) {
    return DateFormat('yyMM').format(dateTime);
  }

  /// Format time for file ID (HHMMSS)
  static String formatTimeForId(DateTime dateTime) {
    return DateFormat('HHmmss').format(dateTime);
  }

  /// Parse YYMM directory name to DateTime
  static DateTime? parseDirectoryMonth(String dirName) {
    try {
      if (dirName.length == 4) {
        final year = int.parse('20${dirName.substring(0, 2)}');
        final month = int.parse(dirName.substring(2, 4));
        return DateTime(year, month);
      }
    } catch (e) {
      // Invalid format
    }
    return null;
  }
}

class ValidationUtils {
  /// Validate IP address format
  static bool isValidIP(String ip) {
    final regex = RegExp(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$');
    if (!regex.hasMatch(ip)) return false;
    
    final parts = ip.split('.');
    for (final part in parts) {
      final num = int.tryParse(part);
      if (num == null || num < 0 || num > 255) return false;
    }
    return true;
  }

  /// Validate port number
  static bool isValidPort(int port) {
    return port > 0 && port <= 65535;
  }

  /// Validate integration time (microseconds)
  static bool isValidIntegrationTime(int time) {
    return time > 0 && time <= 3600000000; // Up to 1 hour
  }

  /// Validate scans to average
  static bool isValidScansToAverage(int scans) {
    return scans > 0 && scans <= 1000;
  }

  /// Validate collection interval (milliseconds)
  static bool isValidCollectionInterval(int interval) {
    return interval >= 100; // Minimum 100ms
  }
}

class FormatUtils {
  /// Format file size for display
  static String formatFileSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    if (bytes < 1024 * 1024 * 1024) return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(1)} GB';
  }

  /// Format duration for display
  static String formatDuration(Duration duration) {
    final hours = duration.inHours;
    final minutes = duration.inMinutes % 60;
    final seconds = duration.inSeconds % 60;
    
    if (hours > 0) {
      return '${hours}h ${minutes}m ${seconds}s';
    } else if (minutes > 0) {
      return '${minutes}m ${seconds}s';
    } else {
      return '${seconds}s';
    }
  }

  /// Format number with appropriate precision
  static String formatNumber(double value, {int? precision}) {
    if (precision != null) {
      return value.toStringAsFixed(precision);
    }
    
    if (value.abs() >= 1000) {
      return value.toStringAsFixed(0);
    } else if (value.abs() >= 100) {
      return value.toStringAsFixed(1);
    } else {
      return value.toStringAsFixed(2);
    }
  }
}

class ColorUtils {
  /// Get status color based on condition
  static Color getStatusColor(bool isOk) {
    return isOk ? Colors.green : Colors.red;
  }

  /// Get value color based on sensor type and value
  static Color getSensorValueColor(String deviceType, double value) {
    switch (deviceType.toUpperCase()) {
      case 'PH':
        if (value < 6.5 || value > 8.5) return Colors.red.shade600;
        return Colors.blue.shade600;
      case 'TEMP':
      case 'PT100':
        if (value < 0 || value > 50) return Colors.orange.shade700;
        return Colors.orange.shade600;
      case 'DDL':
        if (value < 2) return Colors.red.shade600;
        return Colors.green.shade600;
      default:
        return Colors.black87;
    }
  }
}
