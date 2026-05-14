import 'package:flutter_test/flutter_test.dart';
import 'package:hy_app/models/device_reset.dart';
import 'package:hy_app/providers/device_reset_provider.dart';

void main() {
  group('DeviceResetProvider Tests', () {
    late DeviceResetProvider provider;

    setUp(() {
      provider = DeviceResetProvider();
    });

    tearDown(() {
      provider.dispose();
    });

    test('初始状态应该正确', () {
      expect(provider.resetState, ResetState.idle);
      expect(provider.selectedRegister, 0);
      expect(provider.autoResetOnError, false);
      expect(provider.sensorErrorCount, 0);
      expect(provider.isResetting, false);
      expect(provider.resetProgress, 0.0);
    });

    test('设置寄存器地址应该工作', () {
      provider.setSelectedRegister(5);
      expect(provider.selectedRegister, 5);

      // 测试边界值
      provider.setSelectedRegister(0);
      expect(provider.selectedRegister, 0);

      provider.setSelectedRegister(7);
      expect(provider.selectedRegister, 7);

      // 测试无效值（应该被忽略）
      provider.setSelectedRegister(-1);
      expect(provider.selectedRegister, 7); // 应该保持之前的值

      provider.setSelectedRegister(8);
      expect(provider.selectedRegister, 7); // 应该保持之前的值
    });

    test('自动重置开关应该工作', () {
      expect(provider.autoResetOnError, false);
      
      provider.setAutoResetOnError(true);
      expect(provider.autoResetOnError, true);

      provider.setAutoResetOnError(false);
      expect(provider.autoResetOnError, false);
    });

    test('传感器错误计数应该正确工作', () {
      expect(provider.sensorErrorCount, 0);
      expect(provider.shouldAutoReset, false);

      // 启用自动重置
      provider.setAutoResetOnError(true);
      expect(provider.shouldAutoReset, false); // 错误次数不够

      // 增加错误计数
      provider.incrementSensorErrorCount();
      expect(provider.sensorErrorCount, 1);
      expect(provider.shouldAutoReset, false);

      provider.incrementSensorErrorCount();
      expect(provider.sensorErrorCount, 2);
      expect(provider.shouldAutoReset, false);

      provider.incrementSensorErrorCount();
      expect(provider.sensorErrorCount, 3);
      expect(provider.shouldAutoReset, true); // 达到阈值

      // 重置错误计数
      provider.resetSensorErrorCount();
      expect(provider.sensorErrorCount, 0);
      expect(provider.shouldAutoReset, false);
    });

    test('清除重置状态应该工作', () {
      // 模拟设置一些状态
      provider.setSelectedRegister(3);
      provider.setAutoResetOnError(true);
      provider.incrementSensorErrorCount();

      // 清除状态应该只清除重置相关的状态，保留配置
      provider.clearResetState();
      
      expect(provider.resetState, ResetState.idle);
      expect(provider.currentTaskId, null);
      expect(provider.currentStatus, null);
      expect(provider.resetError, null);
      
      // 配置应该保留
      expect(provider.selectedRegister, 3);
      expect(provider.autoResetOnError, true);
      expect(provider.sensorErrorCount, 1); // 错误计数也应该保留
    });
  });

  group('DeviceMode Tests', () {
    test('DeviceMode.fromJson 应该正确解析', () {
      final json = {
        'mode': 'mock',
        'description': '模拟设备模式 (Mock Mode)',
        'is_mock': true,
      };

      final deviceMode = DeviceMode.fromJson(json);
      
      expect(deviceMode.mode, 'mock');
      expect(deviceMode.description, '模拟设备模式 (Mock Mode)');
      expect(deviceMode.isMock, true);
    });

    test('DeviceMode.fromJson 应该处理缺失字段', () {
      final json = <String, dynamic>{};

      final deviceMode = DeviceMode.fromJson(json);
      
      expect(deviceMode.mode, '');
      expect(deviceMode.description, '');
      expect(deviceMode.isMock, false);
    });
  });

  group('DeviceResetRequest Tests', () {
    test('toJson 应该正确序列化', () {
      const request = DeviceResetRequest(
        ip: '192.168.1.100',
        port: 502,
        register: 5,
        mockMode: true,
      );

      final json = request.toJson();
      
      expect(json['ip'], '192.168.1.100');
      expect(json['port'], 502);
      expect(json['register'], 5);
      expect(json['mock_mode'], true);
    });
  });

  group('DeviceResetStatus Tests', () {
    test('DeviceResetStatus.fromJson 应该正确解析', () {
      final json = {
        'task_id': 'test-123',
        'status': 'running',
        'duration_seconds': 15.5,
        'result': {'test': 'data'},
        'error': null,
        'estimated_remaining': 20.0,
        'estimated_total': 35.5,
      };

      final status = DeviceResetStatus.fromJson(json);
      
      expect(status.taskId, 'test-123');
      expect(status.status, 'running');
      expect(status.durationSeconds, 15.5);
      expect(status.result, {'test': 'data'});
      expect(status.error, null);
      expect(status.estimatedRemaining, 20.0);
      expect(status.estimatedTotal, 35.5);
      
      expect(status.isRunning, true);
      expect(status.isCompleted, false);
      expect(status.isFailed, false);
      expect(status.progress, closeTo(0.437, 0.001)); // 15.5 / 35.5
    });

    test('状态检查方法应该正确工作', () {
      var status = DeviceResetStatus.fromJson({'status': 'running'});
      expect(status.isRunning, true);
      expect(status.isCompleted, false);
      expect(status.isFailed, false);

      status = DeviceResetStatus.fromJson({'status': 'completed'});
      expect(status.isRunning, false);
      expect(status.isCompleted, true);
      expect(status.isFailed, false);

      status = DeviceResetStatus.fromJson({'status': 'failed'});
      expect(status.isRunning, false);
      expect(status.isCompleted, false);
      expect(status.isFailed, true);
    });

    test('进度计算应该正确', () {
      // 正常情况
      var status = DeviceResetStatus.fromJson({
        'duration_seconds': 10.0,
        'estimated_total': 30.0,
      });
      expect(status.progress, closeTo(0.333, 0.001));

      // 超过总时间
      status = DeviceResetStatus.fromJson({
        'duration_seconds': 40.0,
        'estimated_total': 30.0,
      });
      expect(status.progress, 1.0);

      // 没有总时间估计
      status = DeviceResetStatus.fromJson({
        'duration_seconds': 10.0,
      });
      expect(status.progress, 0.0);

      // 总时间为0或负数
      status = DeviceResetStatus.fromJson({
        'duration_seconds': 10.0,
        'estimated_total': 0.0,
      });
      expect(status.progress, 0.0);
    });
  });
}
