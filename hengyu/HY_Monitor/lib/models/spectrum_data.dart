import 'package:fl_chart/fl_chart.dart';

class SpectrumData {
  SpectrumData({
    required this.x,
    required this.y,
    required this.xlabel,
    required this.ylabel,
  });

  final List<double> x;
  final List<double> y;
  final String xlabel;
  final String ylabel;

  factory SpectrumData.fromJson(Map<String, dynamic> json) {
    return SpectrumData(
      x: _toDoubleList(json['x']),
      y: _toDoubleList(json['y']),
      xlabel: (json['xlabel'] ?? '波长(nm)').toString(),
      ylabel: (json['ylabel'] ?? '强度').toString(),
    );
  }

  int get pointCount => x.length < y.length ? x.length : y.length;

  List<FlSpot> get spots {
    final count = pointCount;
    return [
      for (var i = 0; i < count; i++) FlSpot(x[i], y[i]),
    ];
  }

  static List<double> _toDoubleList(dynamic value) {
    if (value is! List) return const [];
    return value
        .map((e) {
          if (e is num) return e.toDouble();
          return double.tryParse(e.toString());
        })
        .whereType<double>()
        .where((e) => e.isFinite)
        .toList(growable: false);
  }
}
