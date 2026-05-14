import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:path_provider/path_provider.dart';
import 'package:provider/provider.dart';

import '../models/spc_search_result.dart';
import '../models/spc_file_info.dart';
import '../providers/devices_provider.dart';
import '../providers/settings_provider.dart';
import '../services/api_service.dart';

/// 光谱检索页：跨设备、按日期范围搜索所有 SPC 文件（采样光谱 + 参比光谱）。
class SpectrumSearchScreen extends StatefulWidget {
  const SpectrumSearchScreen({super.key});

  @override
  State<SpectrumSearchScreen> createState() => _SpectrumSearchScreenState();
}

class _SpectrumSearchScreenState extends State<SpectrumSearchScreen> {
  static final _dateFmt = DateFormat('yyyy-MM-dd');

  DateTimeRange? _dateRange;
  String? _selectedDeviceId;
  String? _selectedSpcType; // null = 全部

  List<SpcSearchResult> _results = const [];
  bool _loading = false;
  String? _error;
  bool _searched = false;

  static const _typeOptions = <String, String>{
    'sample': '采样光谱',
    'blank_before': '置换前参比',
    'blank_after': '清洗后参比',
  };

  ApiService _buildApi(BuildContext context) {
    return ApiService(context.read<SettingsProvider>().baseUrl);
  }

  Future<void> _pickDateRange() async {
    final now = DateTime.now();
    final picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2020),
      lastDate: now,
      initialDateRange: _dateRange ??
          DateTimeRange(
            start: now.subtract(const Duration(days: 30)),
            end: now,
          ),
      locale: const Locale('zh'),
      helpText: '选择检索日期范围',
      cancelText: '取消',
      confirmText: '确定',
      saveText: '确定',
    );
    if (picked != null && mounted) {
      setState(() => _dateRange = picked);
    }
  }

  Future<void> _doSearch() async {
    setState(() {
      _loading = true;
      _error = null;
      _results = const [];
    });

    try {
      final api = _buildApi(context);
      final results = await api.searchSpc(
        dateFrom: _dateRange?.start,
        dateTo: _dateRange?.end,
        deviceId: _selectedDeviceId,
        spcType: _selectedSpcType,
      );
      if (mounted) {
        setState(() {
          _results = results;
          _searched = true;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _reset() {
    setState(() {
      _dateRange = null;
      _selectedDeviceId = null;
      _selectedSpcType = null;
      _results = const [];
      _error = null;
      _searched = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('光谱检索'),
        actions: [
          if (_searched || _dateRange != null)
            IconButton(
              tooltip: '重置',
              icon: const Icon(Icons.restart_alt),
              onPressed: _reset,
            ),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _buildFilterPanel(context, theme),
          const Divider(height: 1),
          Expanded(child: _buildBody(context, theme)),
        ],
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // 筛选面板
  // ---------------------------------------------------------------------------

  Widget _buildFilterPanel(BuildContext context, ThemeData theme) {
    final hasDate = _dateRange != null;
    final dateLabel = hasDate
        ? '${_dateFmt.format(_dateRange!.start)}  —  ${_dateFmt.format(_dateRange!.end)}'
        : '选择日期范围（必填）';

    final deviceIds = context.watch<DevicesProvider>().deviceIds;

    return Container(
      color: theme.colorScheme.surfaceContainerLow,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // 日期选择行
          Row(
            children: [
              Expanded(
                child: FilledButton.tonalIcon(
                  onPressed: _pickDateRange,
                  icon: Icon(
                    Icons.date_range,
                    size: 18,
                    color: hasDate ? theme.colorScheme.primary : null,
                  ),
                  label: Text(
                    dateLabel,
                    style: TextStyle(
                      color: hasDate ? theme.colorScheme.primary : null,
                      fontWeight:
                          hasDate ? FontWeight.w600 : FontWeight.normal,
                    ),
                  ),
                  style: FilledButton.styleFrom(
                    alignment: Alignment.centerLeft,
                    padding:
                        const EdgeInsets.symmetric(vertical: 12, horizontal: 14),
                  ),
                ),
              ),
              if (hasDate) ...[
                const SizedBox(width: 6),
                IconButton(
                  tooltip: '清除日期',
                  icon: const Icon(Icons.close, size: 20),
                  onPressed: () => setState(() => _dateRange = null),
                ),
              ],
            ],
          ),
          const SizedBox(height: 10),
          // 设备 + 类型行
          Row(
            children: [
              Expanded(
                child: _buildDeviceDropdown(context, theme, deviceIds),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _buildTypeDropdown(context, theme),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // 检索按钮
          FilledButton.icon(
            onPressed: _loading ? null : _doSearch,
            icon: _loading
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.search),
            label: Text(_loading ? '检索中…' : '开始检索'),
          ),
        ],
      ),
    );
  }

  Widget _buildDeviceDropdown(
    BuildContext context,
    ThemeData theme,
    List<String> deviceIds,
  ) {
    return DropdownButtonFormField<String?>(
      value: _selectedDeviceId,
      isExpanded: true,
      decoration: const InputDecoration(
        labelText: '设备',
        isDense: true,
        border: OutlineInputBorder(),
        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      ),
      items: [
        const DropdownMenuItem<String?>(value: null, child: Text('全部设备')),
        for (final id in deviceIds)
          DropdownMenuItem<String?>(value: id, child: Text(id, overflow: TextOverflow.ellipsis)),
      ],
      onChanged: (v) => setState(() => _selectedDeviceId = v),
    );
  }

  Widget _buildTypeDropdown(BuildContext context, ThemeData theme) {
    return DropdownButtonFormField<String?>(
      value: _selectedSpcType,
      isExpanded: true,
      decoration: const InputDecoration(
        labelText: '光谱类型',
        isDense: true,
        border: OutlineInputBorder(),
        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      ),
      items: [
        const DropdownMenuItem<String?>(value: null, child: Text('全部类型')),
        for (final e in _typeOptions.entries)
          DropdownMenuItem<String?>(value: e.key, child: Text(e.value)),
      ],
      onChanged: (v) => setState(() => _selectedSpcType = v),
    );
  }

  // ---------------------------------------------------------------------------
  // 结果区
  // ---------------------------------------------------------------------------

  Widget _buildBody(BuildContext context, ThemeData theme) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return _ErrorState(message: _error!, onRetry: _doSearch);
    }
    if (!_searched) {
      return _HintState();
    }
    if (_results.isEmpty) {
      return _EmptyState(
        hasFilter: _dateRange != null ||
            _selectedDeviceId != null ||
            _selectedSpcType != null,
      );
    }
    return _ResultList(results: _results);
  }
}

// ---------------------------------------------------------------------------
// 结果列表
// ---------------------------------------------------------------------------

class _ResultList extends StatelessWidget {
  const _ResultList({required this.results});

  final List<SpcSearchResult> results;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: results.length + 1,
      itemBuilder: (context, i) {
        if (i == 0) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Text(
              '共找到 ${results.length} 条光谱记录',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
          );
        }
        final r = results[i - 1];
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: _ResultTile(result: r),
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// 单条结果 Tile
// ---------------------------------------------------------------------------

class _ResultTile extends StatelessWidget {
  const _ResultTile({required this.result});

  final SpcSearchResult result;

  static const _typeColors = {
    'sample': Colors.blue,
    'blank_before': Colors.orange,
    'blank_after': Colors.green,
  };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final typeColor =
        _typeColors[result.spcType] ?? theme.colorScheme.secondary;
    final info = result.fileInfo;

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.6)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: typeColor.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(Icons.insert_drive_file_outlined, color: typeColor),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: typeColor.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          result.typeLabel,
                          style: TextStyle(
                            fontSize: 11,
                            color: typeColor,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          result.deviceId,
                          style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.outline),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    info.storedFilename,
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(fontWeight: FontWeight.w600),
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${info.readableSize}  ·  ${info.serverTime}',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.outline),
                  ),
                ],
              ),
            ),
            IconButton(
              tooltip: '下载',
              icon: const Icon(Icons.download),
              onPressed: () => _download(context),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _download(BuildContext context) async {
    final settings = context.read<SettingsProvider>();
    final api = ApiService(settings.baseUrl);
    final messenger = ScaffoldMessenger.of(context);
    messenger.showSnackBar(const SnackBar(
      content: Text('正在下载…'),
      duration: Duration(seconds: 1),
    ));
    try {
      late final (String, Uint8List) fetched;
      if (result.spcType == 'sample') {
        fetched = await api.downloadSpcByName(
            result.deviceId, result.fileInfo.storedFilename);
      } else {
        fetched = await api.downloadBlankSpcByName(
            result.deviceId, result.spcType, result.fileInfo.storedFilename);
      }
      final (filename, bytes) = fetched;
      final saved = await _saveBytes(filename, bytes);
      messenger.showSnackBar(SnackBar(
        content: Text('已保存至: $saved'),
        duration: const Duration(seconds: 4),
      ));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('下载失败: $e')));
    }
  }
}

// ---------------------------------------------------------------------------
// 空态 / 提示 / 错误
// ---------------------------------------------------------------------------

class _HintState extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.manage_search_rounded,
                size: 64, color: theme.colorScheme.outline),
            const SizedBox(height: 16),
            Text('按日期检索光谱文件',
                style: theme.textTheme.titleMedium
                    ?.copyWith(fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            Text(
              '选择日期范围，可选择设备和光谱类型\n点击「开始检索」查找 SPC 文件',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.hasFilter});
  final bool hasFilter;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.inbox_outlined,
                size: 64, color: theme.colorScheme.outline),
            const SizedBox(height: 12),
            Text(
              hasFilter ? '所选条件下暂无光谱文件' : '后端暂无光谱文件记录',
              style: theme.textTheme.titleMedium,
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline,
                size: 56, color: theme.colorScheme.error),
            const SizedBox(height: 12),
            Text('检索失败',
                style: theme.textTheme.titleMedium
                    ?.copyWith(color: theme.colorScheme.error)),
            const SizedBox(height: 8),
            Text(
              message,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
            const SizedBox(height: 16),
            FilledButton.tonalIcon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 下载辅助（桌面端弹 saveFile 对话框，移动端写文档目录）
// ---------------------------------------------------------------------------

Future<String> _saveBytes(String filename, Uint8List bytes) async {
  if (Platform.isWindows || Platform.isMacOS || Platform.isLinux) {
    final path = await FilePicker.platform.saveFile(
      dialogTitle: '保存 SPC 文件',
      fileName: filename,
      type: FileType.custom,
      allowedExtensions: const ['spc'],
      bytes: bytes,
    );
    if (path == null || path.isEmpty) throw '用户取消保存';
    if (!await File(path).exists()) {
      await File(path).writeAsBytes(bytes);
    }
    return path;
  }
  final dir = await getApplicationDocumentsDirectory();
  final file = File('${dir.path}${Platform.pathSeparator}$filename');
  await file.writeAsBytes(bytes);
  return file.path;
}
