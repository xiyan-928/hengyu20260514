import 'package:flutter/material.dart';

/// 用卡片网格展示阀门开关状态，风格与 MetricCard 一致。
class ValveChipPanel extends StatelessWidget {
  const ValveChipPanel({super.key, required this.valves});

  final Map<String, bool> valves;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (valves.isEmpty) {
      return Text(
        '暂无阀门数据',
        style:
            theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.outline),
      );
    }
    final keys = valves.keys.toList()..sort();
    return LayoutBuilder(
      builder: (context, cst) {
        final w = cst.maxWidth;
        final cross = w > 900 ? 6 : (w > 560 ? 3 : 2);
        return GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: cross,
            crossAxisSpacing: 10,
            mainAxisSpacing: 10,
            mainAxisExtent: 100,
          ),
          itemCount: keys.length,
          itemBuilder: (_, i) {
            final k = keys[i];
            final open = valves[k] == true;
            final accent =
                open ? Colors.green : theme.colorScheme.outlineVariant;
            final accentStrong =
                open ? Colors.green.shade700 : theme.colorScheme.outline;
            return Card(
              elevation: 0,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
                side: BorderSide(
                  color: accent.withValues(alpha: 0.4),
                ),
              ),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.all(5),
                          decoration: BoxDecoration(
                            color: accent.withValues(alpha: 0.12),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Icon(
                            open
                                ? Icons.check_circle_outline
                                : Icons.cancel_outlined,
                            size: 16,
                            color: accentStrong,
                          ),
                        ),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            k,
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.outline,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                    Text(
                      open ? '开' : '关',
                      style: theme.textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                        color: accentStrong,
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }
}
