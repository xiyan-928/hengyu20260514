import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:path_provider/path_provider.dart';
import 'package:provider/provider.dart';

import '../models/batch_info.dart';
import '../models/spc_file_info.dart';
import '../models/spectrum_data.dart';
import '../providers/device_detail_provider.dart';
import '../providers/settings_provider.dart';
import '../services/api_service.dart';
import '../widgets/process_parameters_sidebar.dart';
import '../widgets/spectrum_plot_window.dart';

/// 参比光谱 SPC 文件列表页，对应 test1.py 的：
///   GET  /spc/blank/device/{id}
///   GET  /spc/blank/device/{id}/{blank_type}/latest
///   GET  /spc/blank/device/{id}/{blank_type}/files/{filename}
class BlankSpcScreen extends StatefulWidget {
  const BlankSpcScreen({super.key, required this.deviceId});

  final String deviceId;

  @override
  State<BlankSpcScreen> createState() => _BlankSpcScreenState();
}

class _BlankSpcScreenState extends State<BlankSpcScreen> {
  static const _blankLabels = {
    'blank_before': '置换前参比光谱',
    'blank_after': '清洗后参比光谱',
  };

  static const _blankIcons = {
    'blank_before': Icons.arrow_back_ios_new,
    'blank_after': Icons.arrow_forward_ios,
  };

  static final _dateFmt = DateFormat('yyyy-MM-dd');

  final Map<String, _BlankPlotEntry> _plotEntries = {};
  String? _plotError;
  int _plotRequestSeq = 0;

  bool get _plotLoading => _plotEntries.values.any((entry) => entry.loading);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      final p = context.read<DeviceDetailProvider>();
      await p.ensureBatchSelected();
      if (!mounted) return;
      await p.refreshBlankSpcFiles();
      if (!mounted) return;
      for (final type in ['blank_before', 'blank_after']) {
        final files = p.blankSpcFiles[type];
        if (files != null && files.isNotEmpty) {
          await _showPlot(type, files.last);
          if (!mounted) return;
        }
      }
    });
  }

  Future<void> _pickDateRange(DeviceDetailProvider p) async {
    final now = DateTime.now();
    final picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2020),
      lastDate: now,
      initialDateRange: p.blankSpcDateFilter ??
          DateTimeRange(
            start: now.subtract(const Duration(days: 30)),
            end: now,
          ),
      locale: const Locale('zh'),
      helpText: '选择参比光谱检索日期范围',
      cancelText: '取消',
      confirmText: '确定',
      saveText: '确定',
    );
    if (picked != null && mounted) {
      await p.setBlankSpcDateFilter(picked);
    }
  }

  Future<void> _clearFilter(DeviceDetailProvider p) =>
      p.setBlankSpcDateFilter(null);

  Future<void> _showPlot(String blankType, SpcFileInfo info) async {
    final seq = _plotRequestSeq;
    final key = _plotKey(blankType, info.storedFilename);
    final existing = _plotEntries[key];
    if (existing != null) {
      setState(() {
        _plotEntries.remove(key);
        _plotError = null;
      });
      return;
    }

    setState(() {
      _plotEntries[key] = _BlankPlotEntry(
        blankType: blankType,
        info: info,
        loading: true,
      );
      _plotError = null;
    });

    try {
      final settings = context.read<SettingsProvider>();
      final batch = context.read<DeviceDetailProvider>().selectedBatch;
      final api = ApiService(settings.baseUrl);
      final data = await api.getBlankSpcSpectrumData(
        widget.deviceId,
        blankType,
        info.storedFilename,
        batch: info.batch ?? batch,
      );
      if (!mounted || seq != _plotRequestSeq) return;
      setState(() {
        final entry = _plotEntries[key];
        if (entry != null) {
          entry.data = data;
          entry.loading = false;
        }
      });
    } catch (e) {
      if (!mounted || seq != _plotRequestSeq) return;
      setState(() {
        _plotEntries.remove(key);
        _plotError = _plotEntries.isEmpty ? e.toString() : null;
      });
    }
  }

  void _clearPlot() {
    _plotRequestSeq++;
    setState(() {
      _plotEntries.clear();
      _plotError = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<DeviceDetailProvider>(
      builder: (context, p, _) {
        final metaSource =
            p.displayHistory.isNotEmpty ? p.displayHistory.last : null;
        final sidebar = ProcessParametersSidebar(
          provider: p,
          data: metaSource,
          batchCountKind: BatchSidebarCountKind.blankReference,
        );
        final content = Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(6, 8, 6, 4),
              child: _buildPlotWindow(context),
            ),
            Expanded(
              child: RefreshIndicator(
                onRefresh: p.refreshBlankSpcFiles,
                child: CustomScrollView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  slivers: [
                    SliverPadding(
                      padding: const EdgeInsets.fromLTRB(12, 2, 12, 6),
                      sliver: SliverToBoxAdapter(
                        child: _buildHeaderFilterRow(context, p),
                      ),
                    ),
                    if (p.blankSpcLoading && p.blankSpcFiles.isEmpty)
                      const SliverFillRemaining(
                        hasScrollBody: false,
                        child: Center(child: CircularProgressIndicator()),
                      )
                    else if (p.blankSpcFiles.isEmpty)
                      SliverFillRemaining(
                        hasScrollBody: false,
                        child: _EmptyBody(error: p.blankSpcError),
                      )
                    else
                      // 始终双列：置换前与清洗后左右并排
                      SliverPadding(
                        padding: const EdgeInsets.fromLTRB(6, 0, 6, 8),
                        sliver: SliverToBoxAdapter(
                          child: _buildTwoColSections(p),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ],
        );
        return LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 760;
            return wide
                ? Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        SizedBox(width: 252, child: sidebar),
                        const SizedBox(width: 12),
                        Expanded(child: content),
                      ],
                    ),
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
                        child: sidebar,
                      ),
                      Expanded(child: content),
                    ],
                  );
          },
        );
      },
    );
  }

  // ---------------------------------------------------------------------------
  // 始终双列：置换前与清洗后左右并排
  // ---------------------------------------------------------------------------

  Widget _buildTwoColSections(DeviceDetailProvider p) {
    final types = _blankLabels.keys
        .where((t) => p.blankSpcFiles.containsKey(t))
        .toList();
    if (types.isEmpty) return const SizedBox.shrink();

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (int i = 0; i < types.length; i++) ...[
          if (i > 0) const SizedBox(width: 16),
          Expanded(
            child: _BlankTypeSection(
              deviceId: widget.deviceId,
              blankType: types[i],
              label: _blankLabels[types[i]]!,
              icon: _blankIcons[types[i]]!,
              files: p.blankSpcFiles[types[i]] ?? const [],
              selectedFilenames: _selectedFilenames(types[i]),
              onPlot: _showPlot,
            ),
          ),
        ],
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // 头部 & 过滤栏
  // ---------------------------------------------------------------------------

  Widget _buildHeaderFilterRow(BuildContext context, DeviceDetailProvider p) {
    return Row(
      children: [
        Expanded(
          child: _buildHeader(context, p),
        ),
        const SizedBox(width: 10),
        _buildFilterButton(context, p),
      ],
    );
  }

  Widget _buildHeader(BuildContext context, DeviceDetailProvider p) {
    final theme = Theme.of(context);
    final count = p.blankSpcFiles.values.fold(0, (s, l) => s + l.length);
    final hasFilter = p.blankSpcDateFilter != null;
    final countLabel = hasFilter
        ? '检索到 $count 条参比光谱记录'
        : '共 $count 条参比光谱记录';

    return Card(
      margin: EdgeInsets.zero,
      elevation: 0,
      color: theme.colorScheme.tertiaryContainer.withValues(alpha: 0.4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        child: Row(
          children: [
            Icon(Icons.science_outlined,
                color: theme.colorScheme.tertiary, size: 24),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                countLabel,
                style: theme.textTheme.titleSmall
                    ?.copyWith(fontWeight: FontWeight.w700),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFilterButton(BuildContext context, DeviceDetailProvider p) {
    final theme = Theme.of(context);
    final hasFilter = p.blankSpcDateFilter != null;
    final label = hasFilter
        ? '${_dateFmt.format(p.blankSpcDateFilter!.start)}  —  ${_dateFmt.format(p.blankSpcDateFilter!.end)}'
        : '按日期检索参比光谱';

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton.outlined(
          tooltip: label,
          onPressed: p.blankSpcLoading ? null : () => _pickDateRange(p),
          color: hasFilter ? theme.colorScheme.tertiary : null,
          style: IconButton.styleFrom(
            side: hasFilter
                ? BorderSide(color: theme.colorScheme.tertiary, width: 1.5)
                : null,
            backgroundColor: hasFilter
                ? theme.colorScheme.tertiaryContainer.withValues(alpha: 0.35)
                : null,
          ),
          icon: const Icon(Icons.search),
        ),
        if (p.blankSpcLoading) ...[
          const SizedBox(width: 8),
          const SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ],
        if (hasFilter && !p.blankSpcLoading) ...[
          const SizedBox(width: 8),
          IconButton(
            tooltip: '清除检索条件',
            icon: const Icon(Icons.close),
            onPressed: () => _clearFilter(p),
          ),
        ],
      ],
    );
  }

  Widget _buildPlotWindow(BuildContext context) {
    final theme = Theme.of(context);
    final series = _plotEntries.values
        .where((entry) => entry.data != null)
        .toList(growable: false);
    return SpectrumPlotWindow(
      title: series.isEmpty ? '参比光谱叠加窗口' : '参比光谱叠加窗口（${series.length} 条）',
      emptyText: '点击下方多个参比 SPC 文件或“画图”按钮后，横纵坐标数据会在这里叠加显示',
      accentColor: theme.colorScheme.tertiary,
      loading: _plotLoading,
      error: _plotError,
      data: null,
      series: [
        for (var i = 0; i < series.length; i++)
          SpectrumPlotSeries(
            label: _seriesLabel(series[i]),
            data: series[i].data!,
            color: _seriesColor(i),
          ),
      ],
      onClose: _plotEntries.isEmpty ? null : _clearPlot,
    );
  }

  Set<String> _selectedFilenames(String blankType) {
    return _plotEntries.values
        .where((entry) => entry.blankType == blankType)
        .map((entry) => entry.info.storedFilename)
        .toSet();
  }

  String _seriesLabel(_BlankPlotEntry entry) {
    final label = _blankLabels[entry.blankType] ?? entry.blankType;
    return '$label · ${entry.info.storedFilename}';
  }

  Color _seriesColor(int index) {
    const colors = [
      Colors.blue,
      Colors.orange,
      Colors.green,
      Colors.purple,
      Colors.red,
      Colors.teal,
      Colors.brown,
      Colors.pink,
    ];
    return colors[index % colors.length];
  }

  static String _plotKey(String blankType, String filename) =>
      '$blankType::$filename';
}

class _BlankPlotEntry {
  _BlankPlotEntry({
    required this.blankType,
    required this.info,
    required this.loading,
    this.data,
  });

  final String blankType;
  final SpcFileInfo info;
  bool loading;
  SpectrumData? data;
}

// ---------------------------------------------------------------------------
// 双列模式下的分组容器（文件列表用 Column，适合有限高度场景）
// ---------------------------------------------------------------------------

class _BlankTypeSection extends StatelessWidget {
  const _BlankTypeSection({
    required this.deviceId,
    required this.blankType,
    required this.label,
    required this.icon,
    required this.files,
    required this.selectedFilenames,
    required this.onPlot,
  });

  final String deviceId;
  final String blankType;
  final String label;
  final IconData icon;
  final List<SpcFileInfo> files;
  final Set<String> selectedFilenames;
  final void Function(String blankType, SpcFileInfo info) onPlot;

  @override
  Widget build(BuildContext context) {
    final reversed = files.reversed.toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _SectionHeader(
          deviceId: deviceId,
          blankType: blankType,
          label: label,
          icon: icon,
          fileCount: files.length,
        ),
        for (final f in reversed)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: _BlankSpcTile(
              deviceId: deviceId,
              blankType: blankType,
              info: f,
              selected: selectedFilenames.contains(f.storedFilename),
              onPlot: onPlot,
            ),
          ),
        const SizedBox(height: 2),
        const Divider(height: 12),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// 分组标题行（在两种布局中复用）
// ---------------------------------------------------------------------------

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({
    required this.deviceId,
    required this.blankType,
    required this.label,
    required this.icon,
    required this.fileCount,
  });

  final String deviceId;
  final String blankType;
  final String label;
  final IconData icon;
  final int fileCount;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Icon(icon, size: 18, color: theme.colorScheme.secondary),
          const SizedBox(width: 6),
          Text(
            label,
            style: theme.textTheme.titleSmall
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
          const Spacer(),
          Text(
            '$fileCount 个文件',
            style: theme.textTheme.bodySmall
                ?.copyWith(color: theme.colorScheme.outline),
          ),
          const SizedBox(width: 8),
          OutlinedButton.icon(
            onPressed: fileCount == 0 ? null : () => _downloadLatest(context),
            icon: const Icon(Icons.download, size: 16),
            label: const Text('下载最新'),
            style: OutlinedButton.styleFrom(
              visualDensity: VisualDensity.compact,
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              minimumSize: const Size(0, 32),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _downloadLatest(BuildContext context) async {
    final settings = context.read<SettingsProvider>();
    final batch = context.read<DeviceDetailProvider>().selectedBatch;
    final api = ApiService(settings.baseUrl);
    await _handleBlankDownload(
      context,
      () => api.downloadLatestBlankSpc(deviceId, blankType, batch: batch),
    );
  }
}

// ---------------------------------------------------------------------------
// 单条参比光谱文件 Tile
// ---------------------------------------------------------------------------

class _BlankSpcTile extends StatelessWidget {
  const _BlankSpcTile({
    required this.deviceId,
    required this.blankType,
    required this.info,
    required this.selected,
    required this.onPlot,
  });

  final String deviceId;
  final String blankType;
  final SpcFileInfo info;
  final bool selected;
  final void Function(String blankType, SpcFileInfo info) onPlot;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      elevation: 0,
      color: selected
          ? theme.colorScheme.secondaryContainer.withValues(alpha: 0.35)
          : null,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: selected
              ? theme.colorScheme.secondary
              : theme.dividerColor.withValues(alpha: 0.6),
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => onPlot(blankType, info),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: theme.colorScheme.secondary.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(Icons.insert_drive_file_outlined,
                    color: theme.colorScheme.secondary, size: 20),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      info.storedFilename,
                      style: theme.textTheme.bodyLarge
                          ?.copyWith(fontWeight: FontWeight.w600),
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '上传时间 ${info.serverTime}',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: selected ? '取消叠加' : '叠加画图',
                constraints: const BoxConstraints.tightFor(
                  width: 36,
                  height: 36,
                ),
                padding: EdgeInsets.zero,
                visualDensity: VisualDensity.compact,
                icon: const Icon(Icons.show_chart),
                iconSize: 20,
                onPressed: () => onPlot(blankType, info),
              ),
              IconButton(
                tooltip: '下载',
                constraints: const BoxConstraints.tightFor(
                  width: 36,
                  height: 36,
                ),
                padding: EdgeInsets.zero,
                visualDensity: VisualDensity.compact,
                icon: const Icon(Icons.download),
                iconSize: 20,
                onPressed: () => _download(context),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _download(BuildContext context) async {
    final settings = context.read<SettingsProvider>();
    final api = ApiService(settings.baseUrl);
    await _handleBlankDownload(
      context,
      () => api.downloadBlankSpcByName(
        deviceId,
        blankType,
        info.storedFilename,
        batch: info.batch,
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 空状态
// ---------------------------------------------------------------------------

class _EmptyBody extends StatelessWidget {
  const _EmptyBody({this.error});
  final String? error;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 40),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.inbox_outlined,
                size: 56, color: theme.colorScheme.outline),
            const SizedBox(height: 12),
            Text(error ?? '尚未收到该设备的参比光谱 SPC 文件'),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 下载辅助
// ---------------------------------------------------------------------------

Future<void> _handleBlankDownload(
  BuildContext context,
  Future<(String, Uint8List)> Function() fetch,
) async {
  final messenger = ScaffoldMessenger.of(context);
  messenger.showSnackBar(const SnackBar(
    content: Text('正在下载…'),
    duration: Duration(seconds: 1),
  ));
  try {
    final (filename, bytes) = await fetch();
    final saved = await _saveBytes(filename, bytes);
    messenger.showSnackBar(SnackBar(
      content: Text('已保存至: $saved'),
      duration: const Duration(seconds: 4),
    ));
  } catch (e) {
    messenger.showSnackBar(SnackBar(content: Text('下载失败: $e')));
  }
}

Future<String> _saveBytes(String filename, Uint8List bytes) async {
  if (Platform.isWindows || Platform.isMacOS || Platform.isLinux) {
    final path = await FilePicker.platform.saveFile(
      dialogTitle: '保存参比光谱 SPC 文件',
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
