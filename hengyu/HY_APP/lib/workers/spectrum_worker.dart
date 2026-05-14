import 'dart:async';
import 'dart:isolate';
import 'package:http/http.dart' as http;
import 'dart:convert';
import '../services/isolate_service.dart';

/// 光谱数据采集isolate工作函数
void spectrumWorker(IsolateMessage message) async {
  final SendPort mainSendPort = message.sendPort;
  final ReceivePort workerReceivePort = ReceivePort();
  
  // 发送工作端口给主线程
  mainSendPort.send(workerReceivePort.sendPort);
  
  // 解析初始配置
  final config = message.data;
  String baseUrl = config['baseUrl'] ?? 'http://localhost:8000';
  int collectionInterval = config['collectionInterval'] ?? 5000; // milliseconds
  int integrationTime = config['integrationTime'] ?? 10000;
  int scansToAverage = config['scansToAverage'] ?? 3;
  
  bool isCollecting = false;
  Timer? collectionTimer;
  final client = http.Client();
  
  // 发送启动状态消息而不是print
  mainSendPort.send({
    'type': 'status',
    'status': 'initialized',
    'message': 'Spectrum worker started with interval: ${collectionInterval}ms'
  });
  
  // 监听主线程消息
  workerReceivePort.listen((message) async {
    if (message is Map<String, dynamic>) {
      final command = message['command'];
      
      switch (command) {
        case 'start':
          if (!isCollecting) {
            isCollecting = true;
            
            // 首先初始化和配置设备
            try {
              await _initializeDevice(client, baseUrl, mainSendPort);
              await _configureDevice(client, baseUrl, integrationTime, scansToAverage, mainSendPort);
              
              // 开始定时采集
              collectionTimer = Timer.periodic(Duration(milliseconds: collectionInterval), (timer) async {
                if (isCollecting) {
                  await _collectSpectrum(client, baseUrl, mainSendPort);
                }
              });
              
              mainSendPort.send({
                'type': 'status',
                'status': 'collecting',
                'message': 'Started spectrum collection'
              });
            } catch (e) {
              mainSendPort.send({
                'type': 'error',
                'message': 'Failed to start spectrum collection: $e'
              });
            }
          }
          break;
          
        case 'stop':
          isCollecting = false;
          collectionTimer?.cancel();
          collectionTimer = null;
          mainSendPort.send({
            'type': 'status',
            'status': 'stopped',
            'message': 'Stopped spectrum collection'
          });
          break;
          
        case 'updateConfig':
          collectionInterval = message['collectionInterval'] ?? collectionInterval;
          integrationTime = message['integrationTime'] ?? integrationTime;
          scansToAverage = message['scansToAverage'] ?? scansToAverage;
          
          // 如果正在采集，重新配置设备
          if (isCollecting) {
            await _configureDevice(client, baseUrl, integrationTime, scansToAverage, mainSendPort);
            
            // 重启定时器以使用新间隔
            collectionTimer?.cancel();
            collectionTimer = Timer.periodic(Duration(milliseconds: collectionInterval), (timer) async {
              if (isCollecting) {
                await _collectSpectrum(client, baseUrl, mainSendPort);
              }
            });
          }
          break;
      }
    }
  });
}

/// 初始化CDS350设备
Future<void> _initializeDevice(http.Client client, String baseUrl, SendPort sendPort) async {
  try {
    final response = await client.post(
      Uri.parse('$baseUrl/cds350/initialize'),
      headers: {'Content-Type': 'application/json'},
    ).timeout(const Duration(seconds: 10));
    
    if (response.statusCode == 200) {
      sendPort.send({
        'type': 'status',
        'status': 'initialized',
        'message': 'CDS350 initialized successfully'
      });
    } else {
      throw Exception('Initialize failed with status: ${response.statusCode}');
    }
  } catch (e) {
    sendPort.send({
      'type': 'error',
      'message': 'Failed to initialize CDS350: $e'
    });
    rethrow;
  }
}

/// 配置CDS350设备参数
Future<void> _configureDevice(http.Client client, String baseUrl, int integrationTime, int scansToAverage, SendPort sendPort) async {
  try {
    final response = await client.post(
      Uri.parse('$baseUrl/cds350/configure'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'integration_time': integrationTime,
        'scans_to_average': scansToAverage,
      }),
    ).timeout(const Duration(seconds: 5));
    
    if (response.statusCode == 200) {
      sendPort.send({
        'type': 'status',
        'status': 'configured',
        'message': 'CDS350 configured successfully'
      });
    } else {
      throw Exception('Configure failed with status: ${response.statusCode}');
    }
  } catch (e) {
    sendPort.send({
      'type': 'error',
      'message': 'Failed to configure CDS350: $e'
    });
    rethrow;
  }
}

/// 采集单次光谱数据
Future<void> _collectSpectrum(http.Client client, String baseUrl, SendPort sendPort) async {
  try {
    final response = await client.get(
      Uri.parse('$baseUrl/cds350/spectrum?force_new=false'),
      headers: {'accept': 'application/json'},
    ).timeout(const Duration(seconds: 60)); // 光谱采集可能需要更长时间
    
    if (response.statusCode == 200) {
      final data = json.decode(response.body);
      print('🔥 Spectrum worker received API response: ${data.keys}');
      
      // 检查API响应结构
      if (data is Map && data.containsKey('success') && data['success'] == true) {
        final spectrumData = data['data'];
        if (spectrumData is Map) {
          final wavelengths = spectrumData['wavelengths'] as List<dynamic>?;
          final intensities = spectrumData['spectrum'] as List<dynamic>?; // 注意：API字段名是'spectrum'，不是'intensities'
          final acquisitionStatus = spectrumData['acquisition_status'] as Map<String, dynamic>?;
          final lastAcquisitionTime = acquisitionStatus?['last_acquisition_time'] as num?;
          
          print('🔥 Spectrum data structure: wavelengths=${wavelengths?.length ?? 0}, intensities=${intensities?.length ?? 0}, lastAcquisitionTime=${lastAcquisitionTime}');
          
          sendPort.send({
            'type': 'spectrum_data',
            'timestamp': DateTime.now().toIso8601String(),
            'wavelengths': wavelengths?.map((e) => (e as num).toDouble()).toList() ?? [],
            'intensities': intensities?.map((e) => (e as num).toDouble()).toList() ?? [],
            'lastAcquisitionTime': lastAcquisitionTime?.toDouble(),
            'acquisitionStatus': acquisitionStatus,
          });
        } else {
          print('🔥 Unexpected spectrum data structure: ${spectrumData.runtimeType}');
          sendPort.send({
            'type': 'error',
            'message': 'Invalid spectrum data structure'
          });
        }
      } else {
        print('🔥 API response indicates failure: ${data['message'] ?? 'Unknown error'}');
        sendPort.send({
          'type': 'error',
          'message': 'API error: ${data['message'] ?? 'Unknown error'}'
        });
      }
    } else {
      sendPort.send({
        'type': 'error',
        'message': 'Failed to get spectrum data: HTTP ${response.statusCode}'
      });
    }
  } catch (e) {
    print('🔥 Spectrum collection error: $e');
    sendPort.send({
      'type': 'error',
      'message': 'Failed to collect spectrum: $e',
      'error_type': 'spectrum_error', // 添加错误类型标识
    });
  }
}
