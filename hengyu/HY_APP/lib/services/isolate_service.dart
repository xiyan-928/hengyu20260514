import 'dart:async';
import 'dart:isolate';
import 'package:flutter/foundation.dart';

/// 管理独立线程工作的服务类
class IsolateService {
  static IsolateService? _instance;
  static IsolateService get instance => _instance ??= IsolateService._();
  
  IsolateService._();
  
  final Map<String, Isolate> _isolates = {};
  final Map<String, SendPort> _sendPorts = {};
  final Map<String, StreamController<Map<String, dynamic>>> _controllers = {};

  /// 启动一个新的isolate工作线程
  Future<bool> startIsolate(String name, void Function(IsolateMessage) entryPoint, Map<String, dynamic> initialData) async {
    try {
      // 如果isolate已存在，先停止它
      await stopIsolate(name);
      
      // 创建接收端口
      final receivePort = ReceivePort();
      final controller = StreamController<Map<String, dynamic>>.broadcast();
      _controllers[name] = controller;
      
      // 监听isolate消息
      receivePort.listen((message) {
        if (message is Map<String, dynamic>) {
          print('🔥 IsolateService received message for $name: ${message.keys}');
          // 检查controller是否还存在且未关闭
          final controller = _controllers[name];
          if (controller != null && !controller.isClosed) {
            controller.add(message);
            print('🔥 IsolateService added message to controller for $name');
          } else {
            print('🔥 IsolateService ERROR: controller is null or closed for $name');
          }
        } else if (message is SendPort) {
          _sendPorts[name] = message;
        }
      });
      
      // 启动isolate
      final isolate = await Isolate.spawn(
        entryPoint, 
        IsolateMessage(receivePort.sendPort, initialData)
      );
      
      _isolates[name] = isolate;
      return true;
    } catch (e) {
      debugPrint('Failed to start isolate $name: $e');
      return false;
    }
  }
  
  /// 停止isolate
  Future<void> stopIsolate(String name) async {
    final isolate = _isolates[name];
    if (isolate != null) {
      isolate.kill(priority: Isolate.immediate);
      _isolates.remove(name);
      _sendPorts.remove(name);
      
      // 先获取controller引用再移除，避免在关闭期间还有消息到达
      final controller = _controllers.remove(name);
      if (controller != null && !controller.isClosed) {
        await controller.close();
      }
    }
  }
  
  /// 向isolate发送消息
  void sendMessage(String name, Map<String, dynamic> message) {
    final sendPort = _sendPorts[name];
    sendPort?.send(message);
  }
  
  /// 获取isolate消息流
  Stream<Map<String, dynamic>>? getMessageStream(String name) {
    return _controllers[name]?.stream;
  }
  
  /// 停止所有isolate
  Future<void> stopAllIsolates() async {
    final names = _isolates.keys.toList();
    for (final name in names) {
      await stopIsolate(name);
    }
  }
}

/// Isolate消息包装类
class IsolateMessage {
  final SendPort sendPort;
  final Map<String, dynamic> data;
  
  IsolateMessage(this.sendPort, this.data);
}
