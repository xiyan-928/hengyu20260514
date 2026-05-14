import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' show DateTimeRange;

import '../app_config.dart';
import '../models/batch_info.dart';
import '../models/device_data.dart';
import '../models/spc_file_info.dart';
import '../services/api_service.dart';

/// 单个设备的三类数据：实时快照（轮询）、历史记录、SPC 列表。
class DeviceDetailProvider extends ChangeNotifier {
  DeviceDetailProvider(this._api, this.deviceId);

  final ApiService _api;
  final String deviceId;

  DeviceData? _latest;
  List<DeviceData> _history = const [];
  List<SpcFileInfo> _spcFiles = const [];
  Map<String, List<SpcFileInfo>> _blankSpcFiles = const {};

  // 生产批次：列表 + 当前选中 + 该批次记录（null = 显示全部历史）
  List<BatchInfo> _batches = const [];
  String? _selectedBatch;
  List<DeviceData> _batchHistory = const [];
  bool _batchesLoading = false;
  bool _batchHistoryLoading = false;
  String? _batchesError;
  String? _batchHistoryError;

  /// 当前光谱检索的日期范围（null = 不过滤，显示全部）。
  DateTimeRange? _spcDateFilter;
  DateTimeRange? _blankSpcDateFilter;

  bool _latestLoading = false;
  bool _historyLoading = false;
  bool _spcLoading = false;
  bool _blankSpcLoading = false;

  String? _latestError;
  String? _historyError;
  String? _spcError;
  String? _blankSpcError;

  Timer? _latestTimer;
  Duration _latestInterval = const Duration(seconds: 2);

  // dispose() 后置为 true，阻止 in-flight async 回调再调用 notifyListeners()，
  // 避免 Null check operator 异常。
  bool _disposed = false;

  DeviceData? get latest => _latest;
  List<DeviceData> get history => _history;
  List<SpcFileInfo> get spcFiles => _spcFiles;
  Map<String, List<SpcFileInfo>> get blankSpcFiles => _blankSpcFiles;

  List<BatchInfo> get batches => _batches;
  String? get selectedBatch => _selectedBatch;
  List<DeviceData> get batchHistory => _batchHistory;
  bool get batchesLoading => _batchesLoading;
  bool get batchHistoryLoading => _batchHistoryLoading;
  String? get batchesError => _batchesError;
  String? get batchHistoryError => _batchHistoryError;

  /// 历史页/侧栏统一使用：始终展示当前选中批次的记录。
  /// 批次列表为空或加载中时返回空列表。
  List<DeviceData> get displayHistory => _batchHistory;

  bool get displayHistoryLoading =>
      _batchHistoryLoading || (_batchesLoading && _selectedBatch == null);

  String? get displayHistoryError => _batchHistoryError ?? _batchesError;

  DateTimeRange? get spcDateFilter => _spcDateFilter;
  DateTimeRange? get blankSpcDateFilter => _blankSpcDateFilter;

  bool get latestLoading => _latestLoading;
  bool get historyLoading => _historyLoading;
  bool get spcLoading => _spcLoading;
  bool get blankSpcLoading => _blankSpcLoading;

  String? get latestError => _latestError;
  String? get historyError => _historyError;
  String? get spcError => _spcError;
  String? get blankSpcError => _blankSpcError;

  void startLatestPolling({Duration? interval}) {
    if (interval != null) _latestInterval = interval;
    _latestTimer?.cancel();
    _latestTimer = Timer.periodic(_latestInterval, (_) => refreshLatest());
    refreshLatest();
  }

  void updateLatestInterval(Duration interval) {
    if (interval == _latestInterval) return;
    _latestInterval = interval;
    if (_latestTimer != null) startLatestPolling(interval: interval);
  }

  void stopLatestPolling() {
    _latestTimer?.cancel();
    _latestTimer = null;
  }

  /// dispose 后安全通知：in-flight async 完成时若已 disposed 则跳过。
  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> refreshLatest() async {
    if (_disposed || _latestLoading) return;
    _latestLoading = true;
    _safeNotify();
    try {
      _latest = await _api.getLatest(deviceId);
      _latestError = null;
    } catch (e) {
      _latestError = e.toString();
    } finally {
      _latestLoading = false;
      _safeNotify();
    }
  }

  Future<void> refreshHistory() async {
    if (_disposed || _historyLoading) return;
    _historyLoading = true;
    _safeNotify();
    try {
      final all = await _api.getHistory(deviceId);
      if (all.length > AppConfig.maxHistoryPoints) {
        _history = all.sublist(all.length - AppConfig.maxHistoryPoints);
      } else {
        _history = all;
      }
      _historyError = null;
    } catch (e) {
      _historyError = e.toString();
    } finally {
      _historyLoading = false;
      _safeNotify();
    }
  }

  /// 拉取该设备的批次列表。
  ///
  /// [autoSelectLatest] = true 时（仅历史页首次加载使用）：列表非空且当前未选批次，
  /// 自动选中第一项（服务端按 mtime 倒序返回 → 即"最新 / 当前正在采集"那个批次）。
  Future<void> refreshBatches({bool autoSelectLatest = false}) async {
    if (_disposed) return;
    if (_batchesLoading) {
      while (!_disposed && _batchesLoading) {
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }
      if (!_disposed &&
          autoSelectLatest &&
          _selectedBatch == null &&
          _batches.isNotEmpty) {
        await selectBatch(_batches.first.batch);
      }
      return;
    }
    _batchesLoading = true;
    _safeNotify();
    try {
      _batches = await _api.listBatches(deviceId);
      _batchesError = null;
      // 如果当前选中的批次已不存在（被删除/重名），改选最新批次（若有）
      if (_selectedBatch != null &&
          !_batches.any((b) => b.batch == _selectedBatch)) {
        _selectedBatch = null;
        _batchHistory = const [];
        _spcFiles = const [];
        _blankSpcFiles = const {};
      }
    } catch (e) {
      _batchesError = e.toString();
    } finally {
      _batchesLoading = false;
      _safeNotify();
    }
    if (!_disposed &&
        autoSelectLatest &&
        _selectedBatch == null &&
        _batches.isNotEmpty) {
      await selectBatch(_batches.first.batch);
    }
  }

  /// 确保依赖批次的页面（SPC / 参比光谱）可以直接进入并读取数据。
  Future<void> ensureBatchSelected() async {
    if (_disposed) return;
    if (_selectedBatch != null && _selectedBatch!.isNotEmpty) return;
    await refreshBatches(autoSelectLatest: true);
    if (!_disposed && _selectedBatch == null && _batches.isNotEmpty) {
      await selectBatch(_batches.first.batch);
    }
  }

  /// 一键回到"最新（正在采集）批次"。
  Future<void> selectLatestBatch() async {
    if (_batches.isEmpty) {
      await refreshBatches(autoSelectLatest: true);
      return;
    }
    await selectBatch(_batches.first.batch);
  }

  /// 选择批次：按批次名加载对应 CSV 文件的记录并替换 displayHistory。
  Future<void> selectBatch(String batch) async {
    if (batch == _selectedBatch) return;
    _selectedBatch = batch;
    _batchHistoryLoading = true;
    _safeNotify();
    try {
      final all = await _api.getBatchHistory(deviceId, batch);
      if (all.length > AppConfig.maxHistoryPoints) {
        _batchHistory = all.sublist(all.length - AppConfig.maxHistoryPoints);
      } else {
        _batchHistory = all;
      }
      _batchHistoryError = null;
      await _refreshSpcForSelectedBatch();
    } catch (e) {
      _batchHistoryError = e.toString();
    } finally {
      _batchHistoryLoading = false;
      _safeNotify();
    }
  }

  /// 重新加载当前选中的批次（若有）。
  Future<void> refreshSelectedBatch() async {
    final cur = _selectedBatch;
    if (cur == null) return;
    _selectedBatch = null; // 绕过 selectBatch 的 == 检查
    await selectBatch(cur);
  }

  Future<void> refreshSpcFiles() async {
    if (_disposed || _spcLoading) return;
    final batch = _selectedBatch;
    if (batch == null || batch.isEmpty) {
      _spcFiles = const [];
      _spcError = null;
      _safeNotify();
      return;
    }
    _spcLoading = true;
    _safeNotify();
    try {
      _spcFiles = await _api.listSpcFiles(
        deviceId,
        batch: batch,
        dateFrom: _spcDateFilter?.start,
        dateTo: _spcDateFilter?.end,
      );
      _spcError = null;
    } catch (e) {
      _spcError = e.toString();
    } finally {
      _spcLoading = false;
      _safeNotify();
    }
  }

  /// 设置光谱文件的日期检索范围并立即重新拉取。传 null 表示清除过滤、显示全部。
  Future<void> setSpcDateFilter(DateTimeRange? range) async {
    _spcDateFilter = range;
    _safeNotify();
    await refreshSpcFiles();
  }

  Future<void> refreshBlankSpcFiles() async {
    if (_disposed || _blankSpcLoading) return;
    final batch = _selectedBatch;
    if (batch == null || batch.isEmpty) {
      _blankSpcFiles = const {};
      _blankSpcError = null;
      _safeNotify();
      return;
    }
    _blankSpcLoading = true;
    _safeNotify();
    try {
      _blankSpcFiles = await _api.listBlankSpcFiles(
        deviceId,
        batch: batch,
        dateFrom: _blankSpcDateFilter?.start,
        dateTo: _blankSpcDateFilter?.end,
      );
      _blankSpcError = null;
    } catch (e) {
      _blankSpcError = e.toString();
    } finally {
      _blankSpcLoading = false;
      _safeNotify();
    }
  }

  /// 设置参比光谱文件的日期检索范围并立即重新拉取。传 null 表示清除过滤、显示全部。
  Future<void> setBlankSpcDateFilter(DateTimeRange? range) async {
    _blankSpcDateFilter = range;
    _safeNotify();
    await refreshBlankSpcFiles();
  }

  Future<void> _refreshSpcForSelectedBatch() async {
    await Future.wait([
      refreshSpcFiles(),
      refreshBlankSpcFiles(),
    ]);
  }

  @override
  void dispose() {
    _disposed = true;
    stopLatestPolling();
    super.dispose();
  }
}
