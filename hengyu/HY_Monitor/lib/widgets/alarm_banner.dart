import 'package:flutter/material.dart';

class AlarmBanner extends StatelessWidget {
  const AlarmBanner({
    super.key,
    required this.alarming,
    this.lastError,
  });

  final bool alarming;
  final String? lastError;

  @override
  Widget build(BuildContext context) {
    if (!alarming && (lastError == null || lastError!.isEmpty)) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: Colors.green.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.green.withValues(alpha: 0.4)),
        ),
        child: Row(
          children: [
            Icon(Icons.shield_outlined, color: Colors.green.shade700, size: 20),
            const SizedBox(width: 8),
            Text(
              '设备状态正常',
              style: TextStyle(
                color: Colors.green.shade800,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
      );
    }
    final color = alarming ? Colors.red : Colors.orange;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            alarming ? Icons.warning_amber_rounded : Icons.error_outline,
            color: color.shade800,
            size: 22,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  alarming ? '设备处于告警状态' : '存在错误',
                  style: TextStyle(
                    color: color.shade900,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                if (lastError != null && lastError!.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(
                    lastError!,
                    style: TextStyle(color: color.shade800),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
