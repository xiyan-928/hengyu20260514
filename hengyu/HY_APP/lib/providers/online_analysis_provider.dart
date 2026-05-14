import 'package:flutter/material.dart';
import '../models/spectrum_data.dart';

class OnlineAnalysisProvider with ChangeNotifier {
  Function(SpectrumData)? _spectrumDataCallback;

  void setSpectrumDataCallback(Function(SpectrumData) callback) {
    _spectrumDataCallback = callback;
  }

  // 示例方法：模拟接收或处理数据后触发回调
  void updateAnalysisData(SpectrumData data) {
    if (_spectrumDataCallback != null) {
      _spectrumDataCallback!(data);
    }
    notifyListeners();
  }
}








