import 'dart:async';
import 'dart:isolate';
import 'package:http/http.dart' as http;
import 'dart:convert';
import '../services/isolate_service.dart';

/// 传感器数据采集isolate工作函数
void sensorWorker(IsolateMessage message) async {
  final SendPort mainSendPort = message.sendPort;
  final ReceivePort workerReceivePort = ReceivePort();
  
  // 发送工作端口给主线程
  mainSendPort.send(workerReceivePort.sendPort);
  
  // 解析初始配置
  final config = message.data;
  String baseUrl = config['baseUrl'] ?? 'http://localhost:8000';
  int collectionInterval = config['collectionInterval'] ?? 2000; // milliseconds
  String deviceIp = config['deviceIp'] ?? '';
  int devicePort = config['devicePort'] ?? 502;
  List<String> deviceTypes = List<String>.from(config['deviceTypes'] ?? []);
  
  bool isCollecting = false;
  bool deviceTypesLoaded = false;
  Timer? collectionTimer;
  final client = http.Client();
  
  // 发送启动状态消息而不是print
  mainSendPort.send({
    'type': 'status',
    'status': 'initialized',
    'message': 'Sensor worker started with interval: ${collectionInterval}ms, devices: $deviceTypes'
  });

  // 监听主线程消息
  workerReceivePort.listen((message) async {
    if (message is Map<String, dynamic>) {
      final command = message['command'];
      
      switch (command) {
        case 'start':
          if (!isCollecting) {
            // 确保设备类型已加载
            if (!deviceTypesLoaded || deviceTypes.isEmpty) {
              mainSendPort.send({
                'type': 'status',
                'status': 'loading_types',
                'message': 'Loading device types first...'
              });
              
              try {
                final types = await _loadDeviceTypesSync(client, baseUrl);
                deviceTypes = types;
                deviceTypesLoaded = true;
                
                mainSendPort.send({
                  'type': 'device_types',
                  'deviceTypes': deviceTypes,
                });
              } catch (e) {
                mainSendPort.send({
                  'type': 'error',
                  'message': 'Failed to load device types: $e'
                });
                break;
              }
            }
            
            isCollecting = true;
            
            try {
              // 开始定时采集传感器数据
              collectionTimer = Timer.periodic(Duration(milliseconds: collectionInterval), (timer) async {
                if (isCollecting) {
                  await _collectSensorData(client, baseUrl, deviceTypes, deviceIp, devicePort, mainSendPort);
                }
              });
              
              mainSendPort.send({
                'type': 'status',
                'status': 'collecting',
                'message': 'Started sensor data collection with ${deviceTypes.length} devices'
              });
            } catch (e) {
              mainSendPort.send({
                'type': 'error',
                'message': 'Failed to start sensor collection: $e'
              });
            }

          }
          break;        case 'stop':
          isCollecting = false;
          collectionTimer?.cancel();
          collectionTimer = null;
          mainSendPort.send({
            'type': 'status',
            'status': 'stopped',
            'message': 'Stopped sensor data collection'
          });
          break;
          
        case 'updateConfig':
          collectionInterval = message['collectionInterval'] ?? collectionInterval;
          deviceIp = message['deviceIp'] ?? deviceIp;
          devicePort = message['devicePort'] ?? devicePort;
          deviceTypes = List<String>.from(message['deviceTypes'] ?? deviceTypes);
          
          // 如果正在采集，重启定时器以应用新间隔
          if (isCollecting) {
            collectionTimer?.cancel();
            collectionTimer = Timer.periodic(Duration(milliseconds: collectionInterval), (timer) async {
              if (isCollecting) {
                await _collectSensorData(client, baseUrl, deviceTypes, deviceIp, devicePort, mainSendPort);
              }
            });
          }
          break;
          
        case 'loadDeviceTypes':
          try {
            final types = await _loadDeviceTypesSync(client, baseUrl);
            deviceTypes = types;
            deviceTypesLoaded = true;
            
            mainSendPort.send({
              'type': 'device_types',
              'deviceTypes': deviceTypes,
            });
          } catch (e) {
            mainSendPort.send({
              'type': 'error',
              'message': 'Failed to load device types: $e'
            });
          }
          break;
      }
    }
  });
}

/// 同步加载设备类型（返回设备类型列表）
Future<List<String>> _loadDeviceTypesSync(http.Client client, String baseUrl) async {
  final response = await client.get(
    Uri.parse('$baseUrl/hy-device/types'),
  ).timeout(const Duration(seconds: 10));
  
  if (response.statusCode == 200) {
    final data = json.decode(response.body);
    if (data is Map && data.containsKey('success') && data['success'] == true) {
      final responseData = data['data'];
      if (responseData is Map && responseData.containsKey('types')) {
        final deviceTypes = List<String>.from(responseData['types']);
        
        // 过滤掉阀门和光源相关的设备类型
        final filteredTypes = deviceTypes.where((type) {
          final upperType = type.toUpperCase();
          return !upperType.contains('VALVE') && 
                 !upperType.contains('LIGHT') &&
                 !upperType.endsWith('_ON') &&
                 !upperType.endsWith('_OFF');
        }).toList();
        
        return filteredTypes;
      }
    }
  }
  
  throw Exception('Load device types failed with status: ${response.statusCode}');
}

/// 采集传感器数据
Future<void> _collectSensorData(http.Client client, String baseUrl, List<String> deviceTypes, 
    String deviceIp, int devicePort, SendPort sendPort) async {
  
  final Map<String, dynamic> sensorData = {};
  final List<String> errors = [];
  int successCount = 0;
  
  // 查询每个传感器
  for (final deviceType in deviceTypes) {
    try {
      final response = await client.post(
        Uri.parse('$baseUrl/hy-device/query'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({'device_type': deviceType}),
      ).timeout(const Duration(seconds: 10)); // 每个传感器查询超时3秒
      
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        if (data is Map && data.containsKey('success') && data['success'] == true) {
          final responseData = data['data'];
          if (responseData is Map && responseData.containsKey('value')) {
            sensorData[deviceType] = {
              'deviceType': deviceType,
              'value': responseData['value'],
              'unit': _getUnitForDeviceType(deviceType),
              'timestamp': DateTime.now().toIso8601String(),
              'deviceIp': deviceIp,
              'devicePort': devicePort,
            };
            successCount++;
          }
        }
      } else {
        errors.add('$deviceType: HTTP ${response.statusCode}');
      }
    } catch (e) {
      errors.add('$deviceType: $e');
    }
  }
  
  // 发送采集结果
  sendPort.send({
    'type': 'sensor_data',
    'timestamp': DateTime.now().toIso8601String(),
    'data': sensorData,
    'successCount': successCount,
    'totalCount': deviceTypes.length,
    'errors': errors,
  });
  
  // 调试信息
  if (sensorData.isNotEmpty) {
    print('🔥 Worker sent sensor data: ${sensorData.length} sensors');
    for (final entry in sensorData.entries) {
      print('🔥 ${entry.key}: ${entry.value['value']} ${entry.value['unit']}');
    }
  } else {
    print('🔥 Worker: No sensor data collected, errors: $errors');
  }
}

/// 获取设备类型对应的单位
String _getUnitForDeviceType(String deviceType) {
  switch (deviceType.toUpperCase()) {
    case 'PH':
      return 'pH';
    case 'PH_TEMP':
    case 'TEMP':
    case 'PT100':
      return '°C';
    case 'DDL':
      return 'μS/cm';
    default:
      return '';
  }
}
