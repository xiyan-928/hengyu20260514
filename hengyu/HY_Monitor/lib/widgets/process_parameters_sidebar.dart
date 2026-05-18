import 'package:flutter/material.dart';

import '../models/batch_info.dart';
import '../models/device_data.dart';
import '../providers/device_detail_provider.dart';

class ProcessParametersSidebar extends StatelessWidget {
  const ProcessParametersSidebar({
    super.key,
    required this.provider,
    this.data,
    this.batchCountKind = BatchSidebarCountKind.sensor,
  });

  final DeviceDetailProvider provider;
  final DeviceData? data;

  /// 生成单号下拉项中「条数」的含义（历史 / SPC / 参比页各不相同）。
  final BatchSidebarCountKind batchCountKind;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final batch = _selectedBatchInfo;
    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.6)),
      ),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
        child: DefaultTextStyle.merge(
          style: theme.textTheme.bodySmall,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '工艺参数',
                style: theme.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                provider.selectedBatch == null
                    ? '来自最新样本'
                    : '来自单号 ${provider.selectedBatch}',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.outline),
              ),
              const SizedBox(height: 10),
              _BatchSelector(
                provider: provider,
                batchCountKind: batchCountKind,
              ),
              const SizedBox(height: 8),
              _metaRow(theme, '布重 (g)', _numOrDash(
                data?.fabricWeightG ?? batch?.fabricWeightG,
              )),
              const SizedBox(height: 6),
              Text(
                '布',
                style: theme.textTheme.labelMedium?.copyWith(
                  color: theme.colorScheme.outline,
                ),
              ),
              const SizedBox(height: 4),
              _metaRow(theme, '长', _numOrDash(
                data?.fabricLength ?? batch?.fabricLength,
              )),
              _metaRow(theme, '宽', _numOrDash(
                data?.fabricWidth ?? batch?.fabricWidth,
              )),
              _metaRow(theme, '高', _numOrDash(
                data?.fabricHeight ?? batch?.fabricHeight,
              )),
              _metaRow(theme, '厚', _numOrDash(
                data?.fabricThickness ?? batch?.fabricThickness,
              )),
              _metaRow(theme, '密度', _numOrDash(
                data?.fabricDensity ?? batch?.fabricDensity,
              )),
              _metaRow(theme, '材料', _strOrDash(
                data?.fabricMaterial ?? batch?.fabricMaterial,
              )),
              const SizedBox(height: 6),
              _metaRow(theme, '浴比', _numOrDash(
                data?.bathRatio ?? batch?.bathRatio,
              )),
            ],
          ),
        ),
      ),
    );
  }

  BatchInfo? get _selectedBatchInfo {
    final selected = provider.selectedBatch;
    if (selected == null) return null;
    for (final batch in provider.batches) {
      if (batch.batch == selected) return batch;
    }
    return null;
  }

  static String _strOrDash(String? v) => (v == null || v.isEmpty) ? '-' : v;

  static String _numOrDash(double? v) =>
      v == null ? '-' : v.toStringAsFixed(v.truncateToDouble() == v ? 0 : 3);

  static Widget _metaRow(ThemeData theme, String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 72,
            child: Text(
              label,
              style: TextStyle(color: theme.colorScheme.outline),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: theme.textTheme.bodySmall?.copyWith(
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _BatchSelector extends StatelessWidget {
  const _BatchSelector({
    required this.provider,
    required this.batchCountKind,
  });

  final DeviceDetailProvider provider;
  final BatchSidebarCountKind batchCountKind;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final batches = provider.batches;
    final selected = provider.selectedBatch;
    final latestBatchId = batches.isNotEmpty ? batches.first.batch : null;

    Widget itemLabel(BatchInfo b, {required bool isLatest}) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Flexible(
            child: Text(
              '${b.displayLabel} · ${b.countForSidebar(batchCountKind)} 条',
              overflow: TextOverflow.ellipsis,
              style: isLatest
                  ? TextStyle(
                      fontWeight: FontWeight.w600,
                      color: theme.colorScheme.primary,
                    )
                  : null,
            ),
          ),
          if (isLatest) ...[
            const SizedBox(width: 6),
            Icon(
              Icons.fiber_manual_record,
              size: 10,
              color: theme.colorScheme.primary,
            ),
            const SizedBox(width: 2),
            Text(
              '最新',
              style: theme.textTheme.labelSmall?.copyWith(
                color: theme.colorScheme.primary,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ],
      );
    }

    final items = <DropdownMenuItem<String>>[
      for (final b in batches)
        DropdownMenuItem<String>(
          value: b.batch,
          child: itemLabel(b, isLatest: b.batch == latestBatchId),
        ),
      if (selected != null && !batches.any((b) => b.batch == selected))
        DropdownMenuItem<String>(
          value: selected,
          child: Text(selected, overflow: TextOverflow.ellipsis),
        ),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                '生成单号',
                style: TextStyle(color: theme.colorScheme.outline),
              ),
            ),
            if (latestBatchId != null && selected != latestBatchId)
              InkWell(
                onTap: provider.batchHistoryLoading
                    ? null
                    : provider.selectLatestBatch,
                borderRadius: BorderRadius.circular(6),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 6,
                    vertical: 2,
                  ),
                  child: Text(
                    '回到最新',
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.primary,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
          ],
        ),
        const SizedBox(height: 4),
        InputDecorator(
          decoration: InputDecoration(
            isDense: true,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
            ),
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 8,
              vertical: 4,
            ),
          ),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              isExpanded: true,
              value: selected,
              items: items,
              onChanged: provider.batchHistoryLoading
                  ? null
                  : (v) {
                      if (v != null) provider.selectBatch(v);
                    },
              hint: Text(
                latestBatchId == null
                    ? '尚无单号记录'
                    : '最新单号（正在采集）',
              ),
            ),
          ),
        ),
        if (provider.batchesLoading)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Row(
              children: [
                const SizedBox(
                  width: 12,
                  height: 12,
                  child: CircularProgressIndicator(strokeWidth: 1.5),
                ),
                const SizedBox(width: 6),
                Text(
                  '加载单号列表...',
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: theme.colorScheme.outline),
                ),
              ],
            ),
          )
        else if (provider.batchesError != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              '单号列表加载失败',
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: theme.colorScheme.error),
            ),
          ),
      ],
    );
  }
}
