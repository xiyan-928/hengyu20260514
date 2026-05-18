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
import '../services/api_service.dart';
import '../providers/settings_provider.dart';
import '../widgets/process_parameters_sidebar.dart';
import '../widgets/spectrum_plot_window.dart';

// 每行固定高度需要贴近卡片实际高度，否则 SliverFixedExtentList 会在行尾留下空白。
const double _kTileRowHeight = 68.0;

class SpcFilesScreen extends StatefulWidget {
  const SpcFilesScreen({super.key, required this.deviceId});

  final String deviceId;

  @override
  State<SpcFilesScreen> createState() => _SpcFilesScreenState();
}

class _SpcFilesScreenState extends State<SpcFilesScreen> {
  static final _dateFmt = DateFormat('yyyy-MM-dd');

  SpcFileInfo? _selectedPlotFile;
  SpectrumData? _spectrumData;
  String? _plotError;
  bool _plotLoading = false;
  int _plotRequestSeq = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      final p = context.read<DeviceDetailProvider>();
      await p.ensureBatchSelected();
      if (!mounted) return;
      await p.refreshSpcFiles();
      if (!mounted) return;
      if (p.spcFiles.isNotEmpty) {
        await _showPlot(p.spcFiles.last);
      }
    });
  }

  Future<void> _pickDateRange(DeviceDetailProvider p) async {
    final now = DateTime.now();
    final picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2020),
      lastDate: now,
      initialDateRange: p.spcDateFilter ??
          DateTimeRange(
            start: now.subtract(const Duration(days: 30)),
            end: now,
          ),
      locale: const Locale('zh'),
      helpText: '选择光谱检索日期范围',
      cancelText: '取消',
      confirmText: '确定',
      saveText: '确定',
    );
    if (picked != null && mounted) {
      await p.setSpcDateFilter(picked);
    }
  }

  Future<void> _clearFilter(DeviceDetailProvider p) => p.setSpcDateFilter(null);

  Future<void> _showPlot(SpcFileInfo info) async {
    final seq = ++_plotRequestSeq;
    setState(() {
      _selectedPlotFile = info;
      _spectrumData = null;
      _plotError = null;
      _plotLoading = true;
    });

    try {
      final settings = context.read<SettingsProvider>();
      final batch = context.read<DeviceDetailProvider>().selectedBatch;
      final api = ApiService(settings.baseUrl);
      final data = await api.getSpcSpectrumData(
        widget.deviceId,
        info.storedFilename,
        batch: info.batch ?? batch,
      );
      if (!mounted || seq != _plotRequestSeq) return;
      setState(() {
        _spectrumData = data;
        _plotLoading = false;
      });
    } catch (e) {
      if (!mounted || seq != _plotRequestSeq) return;
      setState(() {
        _plotError = e.toString();
        _plotLoading = false;
      });
    }
  }

  void _clearPlot() {
    _plotRequestSeq++;
    setState(() {
      _selectedPlotFile = null;
      _spectrumData = null;
      _plotError = null;
      _plotLoading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<DeviceDetailProvider>(
      builder: (context, p, _) {
        // 用 LayoutBuilder 在 build 阶段确定是否开启双列，
        // 避免在 Sliver 内部再嵌套 LayoutBuilder 引起约束冲突。
        return LayoutBuilder(
          builder: (context, constraints) {
            final twoCol = constraints.maxWidth > 1200;
            final files = p.spcFiles.reversed.toList();
            // 双列时每个 row 包含 2 个文件，行数向上取整
            final rowCount = twoCol
                ? (files.length + 1) ~/ 2
                : files.length;
            final wide = constraints.maxWidth >= 760;
            final metaSource =
                p.displayHistory.isNotEmpty ? p.displayHistory.last : null;
            final sidebar = ProcessParametersSidebar(
              provider: p,
              data: metaSource,
              batchCountKind: BatchSidebarCountKind.spectrumSample,
            );

            final content = Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(6, 8, 6, 4),
                  child: _buildPlotWindow(context),
                ),
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: p.refreshSpcFiles,
                    child: CustomScrollView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      slivers: [
                        SliverPadding(
                          padding: const EdgeInsets.fromLTRB(12, 2, 12, 6),
                          sliver: SliverToBoxAdapter(
                            child: _buildHeaderFilterRow(context, p),
                          ),
                        ),
                        if (p.spcLoading && p.spcFiles.isEmpty)
                          const SliverFillRemaining(
                            hasScrollBody: false,
                            child: Center(child: CircularProgressIndicator()),
                          )
                        else if (p.spcFiles.isEmpty)
                          SliverFillRemaining(
                            hasScrollBody: false,
                            child: _buildEmpty(context, p),
                          )
                        else
                          // SliverFixedExtentList：固定行高，总高度 = itemCount × itemExtent，
                          // 滚动条拖动时直接计算位置，无需 build 所有条目，彻底解决拖动卡死。
                          // 同时仍为懒渲染，只 build 视口内可见的行。
                          SliverPadding(
                            padding: const EdgeInsets.fromLTRB(6, 0, 6, 8),
                            sliver: SliverFixedExtentList(
                              itemExtent: _kTileRowHeight,
                              delegate: SliverChildBuilderDelegate(
                                (context, i) {
                                  if (twoCol) {
                                    final a = files[i * 2];
                                    final bi = i * 2 + 1;
                                    return Padding(
                                      padding:
                                          const EdgeInsets.only(bottom: 6),
                                      child: Row(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Expanded(
                                            child: _SpcTile(
                                              deviceId: widget.deviceId,
                                              info: a,
                                              selected: _selectedPlotFile
                                                      ?.storedFilename ==
                                                  a.storedFilename,
                                              onPlot: _showPlot,
                                            ),
                                          ),
                                          const SizedBox(width: 10),
                                          bi < files.length
                                              ? Expanded(
                                                  child: _SpcTile(
                                                    deviceId: widget.deviceId,
                                                    info: files[bi],
                                                    selected: _selectedPlotFile
                                                            ?.storedFilename ==
                                                        files[bi]
                                                            .storedFilename,
                                                    onPlot: _showPlot,
                                                  ),
                                                )
                                              : const Expanded(
                                                  child: SizedBox()),
                                        ],
                                      ),
                                    );
                                  }
                                  return Padding(
                                    padding: const EdgeInsets.only(bottom: 6),
                                    child: _SpcTile(
                                      deviceId: widget.deviceId,
                                      info: files[i],
                                      selected:
                                          _selectedPlotFile?.storedFilename ==
                                              files[i].storedFilename,
                                      onPlot: _showPlot,
                                    ),
                                  );
                                },
                                childCount: rowCount,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            );
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
    final total = p.spcFiles.length;
    final hasFilter = p.spcDateFilter != null;
    final countLabel = hasFilter
        ? '筛选后 $total 个 SPC 文件'
        : '已存档 $total 个 SPC 文件';

    return Card(
      margin: EdgeInsets.zero,
      elevation: 0,
      color: theme.colorScheme.primaryContainer.withValues(alpha: 0.4),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        child: Row(
          children: [
            Icon(Icons.folder_open,
                color: theme.colorScheme.primary, size: 24),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                countLabel,
                style: theme.textTheme.titleSmall
                    ?.copyWith(fontWeight: FontWeight.w700),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            FilledButton.icon(
              onPressed: total == 0
                  ? null
                  : () => _downloadLatest(context, widget.deviceId),
              icon: const Icon(Icons.download),
              label: const Text('下载最新'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFilterButton(BuildContext context, DeviceDetailProvider p) {
    final theme = Theme.of(context);
    final filter = p.spcDateFilter;
    final hasFilter = filter != null;
    final tooltip = hasFilter
        ? '日期筛选：${_dateFmt.format(filter.start)} — ${_dateFmt.format(filter.end)}'
        : '按日期筛选';

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton.outlined(
          tooltip: tooltip,
          onPressed: () => _pickDateRange(p),
          color: hasFilter ? theme.colorScheme.primary : null,
          style: IconButton.styleFrom(
            side: hasFilter
                ? BorderSide(color: theme.colorScheme.primary, width: 1.5)
                : null,
            backgroundColor: hasFilter
                ? theme.colorScheme.primaryContainer.withValues(alpha: 0.35)
                : null,
          ),
          icon: const Icon(Icons.date_range),
        ),
        if (hasFilter)
          IconButton(
            tooltip: '清除筛选',
            icon: const Icon(Icons.close),
            onPressed: () => _clearFilter(p),
          ),
      ],
    );
  }

  Widget _buildPlotWindow(BuildContext context) {
    final theme = Theme.of(context);
    final file = _selectedPlotFile;
    return SpectrumPlotWindow(
      title: file == null ? 'SPC 光谱数据窗口' : file.storedFilename,
      emptyText: '点击下方 SPC 文件或“画图”按钮后，横纵坐标数据会在这里绘制成曲线',
      accentColor: theme.colorScheme.primary,
      loading: _plotLoading,
      error: _plotError,
      data: _spectrumData,
      onClose: file == null ? null : _clearPlot,
    );
  }

  Widget _buildEmpty(BuildContext context, DeviceDetailProvider p) {
    final theme = Theme.of(context);
    final msg = p.spcDateFilter != null
        ? '所选日期范围内暂无光谱文件'
        : (p.spcError ?? '尚未收到该设备的 SPC 文件');
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 40),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.inbox_outlined,
                size: 56, color: theme.colorScheme.outline),
            const SizedBox(height: 12),
            Text(msg),
          ],
        ),
      ),
    );
  }

  Future<void> _downloadLatest(BuildContext context, String deviceId) async {
    final settings = context.read<SettingsProvider>();
    final batch = context.read<DeviceDetailProvider>().selectedBatch;
    final api = ApiService(settings.baseUrl);
    await _handleDownload(
      context,
      () => api.downloadLatestSpc(deviceId, batch: batch),
    );
  }
}

class _SpcTile extends StatelessWidget {
  const _SpcTile({
    required this.deviceId,
    required this.info,
    required this.selected,
    required this.onPlot,
  });

  final String deviceId;
  final SpcFileInfo info;
  final bool selected;
  final ValueChanged<SpcFileInfo> onPlot;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      elevation: 0,
      color: selected
          ? theme.colorScheme.primaryContainer.withValues(alpha: 0.35)
          : null,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: selected
              ? theme.colorScheme.primary
              : theme.dividerColor.withValues(alpha: 0.6),
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => onPlot(info),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: theme.colorScheme.primary.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(Icons.insert_drive_file_outlined,
                    color: theme.colorScheme.primary, size: 20),
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
                tooltip: '画图',
                constraints: const BoxConstraints.tightFor(
                  width: 36,
                  height: 36,
                ),
                padding: EdgeInsets.zero,
                visualDensity: VisualDensity.compact,
                icon: const Icon(Icons.show_chart),
                iconSize: 20,
                onPressed: () => onPlot(info),
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
    await _handleDownload(
      context,
      () => api.downloadSpcByName(
        deviceId,
        info.storedFilename,
        batch: info.batch,
      ),
    );
  }
}

Future<void> _handleDownload(
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

/// 桌面端（Windows/macOS/Linux）调用系统"另存为"对话框；
/// 移动端写入 `getApplicationDocumentsDirectory`。
Future<String> _saveBytes(String filename, Uint8List bytes) async {
  if (Platform.isWindows || Platform.isMacOS || Platform.isLinux) {
    final path = await FilePicker.platform.saveFile(
      dialogTitle: '保存 SPC 文件',
      fileName: filename,
      type: FileType.custom,
      allowedExtensions: const ['spc'],
      bytes: bytes,
    );
    if (path == null || path.isEmpty) {
      throw '用户取消保存';
    }
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
