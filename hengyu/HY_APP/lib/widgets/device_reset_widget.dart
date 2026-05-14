import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../providers/device_reset_provider.dart';

/// 设备重置控制组件
class DeviceResetWidget extends StatefulWidget {
  final String? deviceIp;
  
  const DeviceResetWidget({
    super.key,
    this.deviceIp,
  });

  @override
  State<DeviceResetWidget> createState() => _DeviceResetWidgetState();
}

class _DeviceResetWidgetState extends State<DeviceResetWidget> {
  final TextEditingController _registerController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _registerController.text = '0';
    
    // 初始化时加载设备模式
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final provider = Provider.of<DeviceResetProvider>(context, listen: false);
      provider.loadDeviceMode();
    });
  }

  @override
  void dispose() {
    _registerController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<DeviceResetProvider>(
      builder: (context, provider, child) {
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 标题和设备模式信息
                _buildHeader(provider),
                const SizedBox(height: 16),
                
                // 寄存器地址输入
                _buildRegisterInput(),
                const SizedBox(height: 16),
                
                // 自动重置开关
                _buildAutoResetSwitch(provider),
                const SizedBox(height: 16),
                
                // 重置按钮
                _buildResetButton(provider),
                const SizedBox(height: 16),
                
                // 重置进度
                if (provider.isResetting) ...[
                  _buildResetProgress(provider),
                  const SizedBox(height: 16),
                ],
                
                // 状态信息
                _buildStatusInfo(provider),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildHeader(DeviceResetProvider provider) {
    return Row(
      children: [
        Icon(
          Icons.settings_backup_restore,
          color: Colors.orange.shade700,
          size: 24,
        ),
        const SizedBox(width: 8),
        const Text(
          '设备重置',
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w600,
          ),
        ),
        const Spacer(),
        if (provider.isLoadingMode)
          const SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          )
        else if (provider.deviceMode != null)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: provider.deviceMode!.isMock 
                  ? Colors.orange.shade100 
                  : Colors.green.shade100,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: provider.deviceMode!.isMock 
                    ? Colors.orange.shade300 
                    : Colors.green.shade300,
              ),
            ),
            child: Text(
              provider.deviceMode!.description,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w500,
                color: provider.deviceMode!.isMock 
                    ? Colors.orange.shade700 
                    : Colors.green.shade700,
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildRegisterInput() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '寄存器地址',
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w500,
          ),
        ),
        const SizedBox(height: 8),
        TextFormField(
          controller: _registerController,
          keyboardType: TextInputType.number,
          inputFormatters: [
            FilteringTextInputFormatter.digitsOnly,
            _RegisterRangeFormatter(),
          ],
          decoration: InputDecoration(
            hintText: '输入寄存器地址 (0-7)',
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
            ),
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 12,
              vertical: 8,
            ),
            suffixText: 'Reg',
          ),
          onChanged: (value) {
            final intValue = int.tryParse(value) ?? 0;
            Provider.of<DeviceResetProvider>(context, listen: false)
                .setSelectedRegister(intValue);
          },
        ),
        const SizedBox(height: 4),
        Text(
          '取值范围: 0-7，只能输入整数',
          style: TextStyle(
            fontSize: 12,
            color: Colors.grey.shade600,
          ),
        ),
      ],
    );
  }

  Widget _buildAutoResetSwitch(DeviceResetProvider provider) {
    return Row(
      children: [
        const Icon(
          Icons.autorenew,
          size: 20,
          color: Colors.blue,
        ),
        const SizedBox(width: 8),
        const Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '自动重置',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
              ),
              Text(
                '传感器读取出错3次以上时自动重置',
                style: TextStyle(
                  fontSize: 12,
                  color: Colors.grey,
                ),
              ),
            ],
          ),
        ),
        Switch(
          value: provider.autoResetOnError,
          onChanged: provider.setAutoResetOnError,
          activeColor: Colors.blue,
        ),
      ],
    );
  }

  Widget _buildResetButton(DeviceResetProvider provider) {
    final bool canReset = !provider.isResetting && !provider.isLoadingReset;
    
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton.icon(
        onPressed: canReset ? () => _startReset(provider) : null,
        icon: provider.isLoadingReset
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white,
                ),
              )
            : const Icon(Icons.restart_alt),
        label: Text(
          provider.isResetting 
              ? '重置中...' 
              : provider.isLoadingReset
                  ? '启动中...'
                  : '开始重置',
          style: const TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w600,
          ),
        ),
        style: ElevatedButton.styleFrom(
          backgroundColor: Colors.orange.shade600,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(vertical: 12),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
          ),
        ),
      ),
    );
  }

  Widget _buildResetProgress(DeviceResetProvider provider) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              '重置进度',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w500,
              ),
            ),
            Text(
              '${(provider.resetProgress * 100).toStringAsFixed(0)}%',
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        LinearProgressIndicator(
          value: provider.resetProgress,
          backgroundColor: Colors.grey.shade300,
          valueColor: AlwaysStoppedAnimation<Color>(Colors.orange.shade600),
        ),
        if (provider.currentStatus != null && provider.currentStatus!.estimatedRemaining != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              '预计剩余时间: ${provider.currentStatus!.estimatedRemaining!.toStringAsFixed(0)}秒',
              style: TextStyle(
                fontSize: 12,
                color: Colors.grey.shade600,
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildStatusInfo(DeviceResetProvider provider) {
    String statusText = '';
    Color statusColor = Colors.grey.shade600;
    IconData statusIcon = Icons.info;

    switch (provider.resetState) {
      case ResetState.idle:
        statusText = '准备就绪';
        statusColor = Colors.grey.shade600;
        statusIcon = Icons.check_circle_outline;
        break;
      case ResetState.resetting:
        statusText = '正在重置设备...';
        statusColor = Colors.orange.shade700;
        statusIcon = Icons.hourglass_empty;
        break;
      case ResetState.completed:
        statusText = '重置已完成';
        statusColor = Colors.green.shade700;
        statusIcon = Icons.check_circle;
        break;
      case ResetState.failed:
        statusText = '重置失败: ${provider.resetError ?? "未知错误"}';
        statusColor = Colors.red.shade700;
        statusIcon = Icons.error;
        break;
    }

    // 显示传感器错误计数信息
    if (provider.autoResetOnError) {
      statusText += '\n传感器错误计数: ${provider.sensorErrorCount}/3';
    }

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: statusColor.withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: statusColor.withOpacity(0.3)),
      ),
      child: Row(
        children: [
          Icon(
            statusIcon,
            color: statusColor,
            size: 20,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              statusText,
              style: TextStyle(
                fontSize: 12,
                color: statusColor,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _startReset(DeviceResetProvider provider) async {
    // 显示确认对话框
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.warning, color: Colors.orange),
            SizedBox(width: 8),
            Text('确认重置'),
          ],
        ),
        content: Text(
          '确定要重置设备吗？\n\n'
          '寄存器地址: ${provider.selectedRegister}\n'
          '设备模式: ${provider.deviceMode?.description ?? "未知"}\n'
          '设备IP: ${widget.deviceIp ?? "默认"}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.orange.shade600,
              foregroundColor: Colors.white,
            ),
            child: const Text('确认重置'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      final success = await provider.startDeviceReset(customIp: widget.deviceIp);
      
      if (mounted) {
        if (success) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('设备重置已启动'),
              backgroundColor: Colors.green,
            ),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('重置启动失败: ${provider.resetError}'),
              backgroundColor: Colors.red,
            ),
          );
        }
      }
    }
  }
}

/// 寄存器地址输入格式化器
class _RegisterRangeFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    if (newValue.text.isEmpty) {
      return newValue;
    }

    final intValue = int.tryParse(newValue.text);
    if (intValue == null || intValue < 0 || intValue > 7) {
      return oldValue;
    }

    return newValue;
  }
}
